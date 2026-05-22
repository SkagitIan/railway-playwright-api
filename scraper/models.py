from pydantic import BaseModel


class UrlRequest(BaseModel):
    url: str


class DiscoveryRunRequest(BaseModel):
    industry: str
    custom_query: str | None = None


class DiscoverySourceResolveRequest(BaseModel):
    item_ids: list[int] | None = None


class DiscoveryClassifyItemsRequest(BaseModel):
    item_ids: list[int] | None = None


class DiscoveryClassificationUpdateRequest(BaseModel):
    industry_fit: str
    confidence: float | None = None
    suggested_industry: str | None = None
    reason: str | None = None
    reject_reason: str | None = None
    signals: list[str] | None = None


class DiscoveryDeleteItemsRequest(BaseModel):
    item_ids: list[int]


class DiscoveryMoveItemsRequest(BaseModel):
    item_ids: list[int]
    target_industry: str


class DiscoveryRunJobsRequest(BaseModel):
    item_ids: list[int]
