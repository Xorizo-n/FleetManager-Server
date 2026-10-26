import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _clean(value):
    return " ".join(value.split()) if isinstance(value, str) else value


class HostTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None

    @field_validator("name", "description", mode="before")
    @classmethod
    def strip_text(cls, value):
        return _clean(value) or None if isinstance(value, str) else value


class HostTagUpdate(HostTagCreate):
    name: str | None = Field(default=None, min_length=1, max_length=64)


class HostTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None = None
    host_count: int = 0
    # Сколько ПК с этим тегом поставлено вручную, а не правилом
    manual_count: int = 0
    rule_count: int = 0
    schedule_count: int = 0


class HostTagModelOut(BaseModel):
    """Модель ПК в парке или из правила: сколько ПК, какой тег ставит правило."""

    manufacturer: str
    model: str
    host_count: int
    rule_id: uuid.UUID | None = None
    tag_id: uuid.UUID | None = None
    # ПК этой модели с ручным тегом — правило на них не действует
    manual_count: int = 0


class HostTagRuleSet(BaseModel):
    manufacturer: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    # None — убрать правило
    tag_id: uuid.UUID | None = None

    @field_validator("manufacturer", "model", mode="before")
    @classmethod
    def strip_text(cls, value):
        return _clean(value)


class HostTagRuleResult(BaseModel):
    # У скольких ПК тег изменился после пересчёта
    retagged: int


class HostTagAssign(BaseModel):
    host_ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    tag_id: uuid.UUID | None = None
    # True — снять ручной тег и вернуть тег по правилу; tag_id тогда не нужен
    by_rule: bool = False

    @model_validator(mode="after")
    def check(self):
        if self.by_rule and self.tag_id is not None:
            raise ValueError("Либо тег, либо «по правилу»")
        return self


class HostTagAssignResult(BaseModel):
    updated: int
