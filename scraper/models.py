from pydantic import BaseModel


class UrlRequest(BaseModel):
    url: str


class DiscoveryRunRequest(BaseModel):
    industry: str
    custom_query: str | None = None


class DiscoverySourceResolveRequest(BaseModel):
    item_ids: list[int] | None = None


class DiscoveryDeleteItemsRequest(BaseModel):
    item_ids: list[int]


class DiscoveryMoveItemsRequest(BaseModel):
    item_ids: list[int]
    target_industry: str


class DiscoveryRunJobsRequest(BaseModel):
    item_ids: list[int]
