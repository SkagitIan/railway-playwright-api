from pydantic import BaseModel


class UrlRequest(BaseModel):
    url: str


class DiscoveryRunRequest(BaseModel):
    industry: str
    custom_query: str | None = None


class DiscoverySourceResolveRequest(BaseModel):
    item_ids: list[int] | None = None


class DiscoveryRunJobsRequest(BaseModel):
    item_ids: list[int]
