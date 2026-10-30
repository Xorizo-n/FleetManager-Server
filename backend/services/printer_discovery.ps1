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
function SnmpRequest([string]$oid, [bool]$next) {
    $vb = Tlv 0x30 ([byte[]]((Tlv 0x06 (Oid $oid)) + [byte[]](5,0)))
    $tag = if ($next) { 0xa1 } else { 0xa0 }
    $pdu = Tlv $tag ([byte[]]([byte[]](2,1,1,2,1,0,2,1,0) + (Tlv 0x30 $vb)))
    return ,(Tlv 0x30 ([byte[]]([byte[]](2,1,1) + (Tlv 4 ([Text.Encoding]::ASCII.GetBytes('public'))) + $pdu)))
}
function SnmpReply([byte[]]$r, [string]$oid, [bool]$next) {
    try {
        $t = ReadTlv $r 0; $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Next; $t = ReadTlv $r $t.Next
        if ($t.Tag -ne 0xa2) { return $null }
        $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Next
        if ($t.Tag -ne 2 -or $t.Length -ne 1 -or $r[$t.Start] -ne 0) { return $null }
        $t = ReadTlv $r $t.Next; $t = ReadTlv $r $t.Next; $t = ReadTlv $r $t.Start; $t = ReadTlv $r $t.Start
        $base = Oid $oid
        if ($t.Tag -ne 6 -or $t.Length -lt $base.Length) { return $null }
        for ($j=0; $j -lt $base.Length; $j++) { if ($r[$t.Start+$j] -ne $base[$j]) { return $null } }
        $index = $null
        if ($next) {
            # hrPrinterStatus is indexed by hrDeviceIndex; decode exactly one BER subidentifier.
            if ($t.Length -le $base.Length -or $t.Length -gt ($base.Length+5)) { return $null }
            $index = [long]0
            for ($j=$base.Length; $j -lt $t.Length; $j++) {
                $v = $r[$t.Start+$j]
                if (($j -lt $t.Length-1 -and -not ($v -band 128)) -or ($j -eq $t.Length-1 -and ($v -band 128))) { return $null }
                $index = ($index -shl 7) + ($v -band 127)
            }
            if ($index -lt 1 -or $index -gt 2147483647) { return $null }
        } elseif ($t.Length -ne $base.Length) { return $null }
        $t = ReadTlv $r $t.Next
        if ($next -and $t.Tag -eq 2 -and $t.Length -gt 0 -and $t.Length -le 4) { return $index }
        if (-not $next -and $t.Tag -eq 4) { return [Text.Encoding]::UTF8.GetString($r, $t.Start, $t.Length).Trim([char]0, ' ') }
        return $null
    } catch { return $null }
}
function SnmpGet([string]$ip, [string]$oid) {
    $msg = SnmpRequest $oid $false
    $udp = New-Object Net.Sockets.UdpClient; $udp.Client.ReceiveTimeout = 1000
    try {
        $udp.Connect($ip, 161); [void]$udp.Send($msg, $msg.Length)
        $ep = New-Object Net.IPEndPoint([Net.IPAddress]::Any, 0); $r = $udp.Receive([ref]$ep)
        return (SnmpReply $r $oid $false)
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
# Probe SNMP directly, including printers that have raw TCP/9100 disabled.
# GETNEXT finds the first hrPrinterStatus irrespective of its hrDeviceIndex.
$statusOid = '1.3.6.1.2.1.25.3.5.1.1'
$request = SnmpRequest $statusOid $true
$probes = @()
try {
    $probes = @(for ($n=[int64]$network+1; $n -lt $broadcast; $n++) {
        $ip=ToIp ([uint32]$n)
        if ($ip -eq $addr.IPAddress) { continue }
        $udp=New-Object Net.Sockets.UdpClient
        try {
            $udp.Connect($ip,161); [void]$udp.Send($request,$request.Length)
            [pscustomobject]@{ Ip=$ip; Client=$udp; Task=$udp.ReceiveAsync() }
        } catch { $udp.Close() }
    })
    Start-Sleep -Milliseconds 3000
    $candidates = @($probes | Where-Object { $_.Task.Status -eq 'RanToCompletion' } | ForEach-Object {
        $index = SnmpReply $_.Task.Result.Buffer $statusOid $true
        if ($null -ne $index) { [pscustomobject]@{ Ip=$_.Ip; Index=$index } }
    })
} finally { $probes | ForEach-Object { $_.Client.Close() } }
$found = @(foreach ($candidate in $candidates) {
    $name = SnmpGet $candidate.Ip '1.3.6.1.2.1.1.5.0'
    $model = SnmpGet $candidate.Ip ('1.3.6.1.2.1.25.3.2.1.3.' + $candidate.Index)
    [pscustomobject]@{ address=$candidate.Ip; name=$name; model=$model }
})
$out = @{ subnet=((ToIp $network) + '/' + $prefix); printers=$found }
'FM_PRINTER_DISCOVERY=' + (ConvertTo-Json -InputObject $out -Compress -Depth 4)
