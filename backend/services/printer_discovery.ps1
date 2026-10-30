$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

# Fixed read-only SNMP v2c GET. We do not change device configuration.
function Tlv([byte]$tag, [byte[]]$value) {
    if ($value.Length -ge 128) { throw 'SNMP value too long' }
    return ,([byte[]](@($tag, $value.Length) + $value))
}
function Oid([string]$value) {
    $parts = @($value.Split('.') | ForEach-Object { [long]$_ })
    $bytes = New-Object 'System.Collections.Generic.List[byte]'
    $bytes.Add([byte](40 * $parts[0] + $parts[1]))
    foreach ($v in $parts[2..($parts.Length-1)]) {
        $chunk = New-Object 'System.Collections.Generic.List[byte]'
        do { $chunk.Insert(0, [byte](($v -band 127) -bor $(if ($chunk.Count) { 128 } else { 0 }))); $v = $v -shr 7 } while ($v -gt 0)
        $bytes.AddRange($chunk)
    }
    return ,$bytes.ToArray()
}
function ReadTlv([byte[]]$b, [int]$i) {
    if ($i + 1 -ge $b.Length) { throw 'Invalid SNMP response' }
    $len = [int]$b[$i + 1]; $start = $i + 2
    if ($len -band 128) { $n = $len -band 127; if ($n -gt 2) { throw 'Invalid SNMP length' }; $len = 0; for ($k=0; $k -lt $n; $k++) { $len = ($len -shl 8) + $b[$start+$k] }; $start += $n }
    if (($start + $len) -gt $b.Length) { throw 'Invalid SNMP response length' }
    return [pscustomobject]@{ Tag=$b[$i]; Start=$start; Length=$len; Next=$start+$len }
}
function SnmpGet([string]$ip, [string]$oid) {
    $vb = Tlv 0x30 ([byte[]]((Tlv 0x06 (Oid $oid)) + [byte[]](5,0)))
    $pdu = Tlv 0xa0 ([byte[]]([byte[]](2,1,1,2,1,0,2,1,0) + (Tlv 0x30 $vb)))
    $msg = Tlv 0x30 ([byte[]]([byte[]](2,1,1) + (Tlv 4 ([Text.Encoding]::ASCII.GetBytes('public'))) + $pdu))
    $udp = New-Object Net.Sockets.UdpClient
    $udp.Client.ReceiveTimeout = 1000
    try {
        $udp.Connect($ip, 161)
        [void]$udp.Send($msg, $msg.Length)
        $ep = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0); $r = $udp.Receive([ref]$ep)
        $t = ReadTlv $r 0; $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Next; $t = ReadTlv $r $t.Next
        if ($t.Tag -ne 0xa2) { return $null }
        $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Next
        if ($t.Tag -ne 2 -or $t.Length -ne 1 -or $r[$t.Start] -ne 0) { return $null }
        $t = ReadTlv $r $t.Next; $t = ReadTlv $r $t.Next; $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Next
        if ($t.Tag -eq 4) { return [Text.Encoding]::UTF8.GetString($r, $t.Start, $t.Length).Trim([char]0, ' ') }
        if ($t.Tag -eq 2 -and $t.Length -gt 0 -and $t.Length -le 4) { return [int]$r[$t.Start] }
        return $null
    } catch { return $null } finally { $udp.Close() }
}
function ToInt([string]$ip) { $b=[Net.IPAddress]::Parse($ip).GetAddressBytes(); [Array]::Reverse($b); [BitConverter]::ToUInt32($b,0) }
function ToIp([uint32]$n) { $b=[BitConverter]::GetBytes($n); [Array]::Reverse($b); ([Net.IPAddress]$b).ToString() }

$cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } | Select-Object -First 1
$addr = $cfg.IPv4Address | Select-Object -First 1
if (-not $addr) { throw 'No active IPv4 adapter with default gateway' }
$prefix = [math]::Max([int]$addr.PrefixLength, 24)
if ($prefix -gt 30) { throw 'Subnet has no usable host addresses' }
$mask = [uint32]([math]::Pow(2,32) - [math]::Pow(2,32-$prefix))
$network = (ToInt $addr.IPAddress) -band $mask
$broadcast = [int64]$network + [int64][math]::Pow(2,32-$prefix) - 1
$probes = @()
try {
    $probes = @(for ($n=[int64]$network+1; $n -lt $broadcast; $n++) {
        $ip=ToIp ([uint32]$n)
        if ($ip -eq $addr.IPAddress) { continue }
        $c=New-Object Net.Sockets.TcpClient
        [pscustomobject]@{ Ip=$ip; Client=$c; Task=$c.ConnectAsync($ip,9100) }
    })
    Start-Sleep -Milliseconds 3000
    $candidates = @($probes | Where-Object { $_.Task.Status -eq 'RanToCompletion' } | ForEach-Object { $_.Ip })
} finally { $probes | ForEach-Object { $_.Client.Close() } }
$found = @(foreach ($ip in $candidates) {
    # hrPrinterStatus confirms that this is a printer, not merely a service on 9100.
    $printerState = SnmpGet $ip '1.3.6.1.2.1.25.3.5.1.1.1'
    if ($null -eq $printerState) { continue }
    $name = SnmpGet $ip '1.3.6.1.2.1.1.5.0'
    $model = SnmpGet $ip '1.3.6.1.2.1.25.3.2.1.3.1'
    [pscustomobject]@{ address=$ip; name=$name; model=$model }
})
$out = @{ subnet=((ToIp $network) + '/' + $prefix); printers=$found }
'FM_PRINTER_DISCOVERY=' + (ConvertTo-Json -InputObject $out -Compress -Depth 4)
