import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, Response, UploadFile, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.core.database import get_db, parse_object_id, serialize_doc
from app.core.limiter import PHOTO_UPLOAD_LIMIT, SENSITIVE_UPLOAD_LIMIT, VIDEO_UPLOAD_LIMIT, limiter, user_or_ip
from app.core.security import get_current_user, get_optional_user, require_roles
from app.utils.file_security import DOCUMENT_TYPES, private_file_response, store_upload
from app.schemas.marketplace import (
    DHAKA_TZ,
    OPEN_OFFER_STATUSES,
    SLOT_MINUTES,
    VISIT_BOOKING_WINDOW_DAYS,
    VISIT_DAY_END_HOUR,
    VISIT_DAY_START_HOUR,
    Comparable,
    DaySlots,
    NeighborhoodStats,
    OfferCreate,
    OfferEventType,
    OfferOut,
    OfferResponse,
    OfferStatus,
    OfferType,
    PriceAnalysis,
    SaleListingIn,
    SaleListingOut,
    SaleSearchParams,
    SaleSearchResult,
    SaleSort,
    SaleStatus,
    SlotOut,
    TitleDocType,
    TitleReviewRequest,
    TitleStatus,
    TitleVaultOut,
    VisitApproval,
    VisitCreate,
    VisitOut,
    VisitStatus,
    VisitStatusUpdate,
    check_token_amount,
    sale_listing_fields,
    sale_listing_to_out,
)
from app.schemas.rental import RentalStatus
from app.schemas.user import Role
from app.services import chat_cards
from app.services.listings import (
    GEO_KEY,
    LISTER_LOOKUP,
    PHOTO_ID_PATTERN,
    SALE_ONLY,
    add_listing_photos,
    area_filter,
    area_label,
    delete_listing_with_deals,
    listing_photo_response,
    listing_video_response,
    load_listing_doc,
    load_own_listing,
    make_cover_photo,
    region_filter,
    remove_listing_photo,
    remove_listing_video,
    resolve_center,
    search_target_area,
    set_listing_video,
)

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])

VISITOR_ROLES = (Role.BACHELOR_TENANT, Role.FAMILY_TENANT, Role.BUYER)

# None keeps $nearSphere's nearest-first order.
_SALE_SORTS = {
    SaleSort.DISTANCE: None,
    SaleSort.PRICE_ASC: {"sale.asking_price": 1, "_id": 1},
    SaleSort.PRICE_DESC: {"sale.asking_price": -1, "_id": 1},
    SaleSort.PPSF_ASC: {"price_per_sqft": 1, "_id": 1},
    SaleSort.NEWEST: {"created_at": -1},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _party(user: dict) -> dict:
    return {"id": user["_id"], "full_name": user["full_name"], "phone": user.get("phone", "")}


# ================================================================ Feature 6: sale listings


def _sale_filter(params: SaleSearchParams) -> dict:
    query: dict = {**SALE_ONLY}
    if params.property_type:
        query["property_type"] = {"$in": [p.value for p in params.property_type]}
    price = {op: v for op, v in (("$gte", params.min_price), ("$lte", params.max_price)) if v is not None}
    if price:
        query["sale.asking_price"] = price
    for field, minimum in (
        ("building.size_sqft", params.min_size),
        ("building.bedrooms", params.min_bedrooms),
        ("sale.parking_slots", params.min_parking),
    ):
        if minimum is not None:
            query[field] = {"$gte": minimum}
    if params.handover_status is not None:
        query["sale.handover_status"] = params.handover_status.value
    if params.verified_title:
        query["title_status"] = TitleStatus.VERIFIED.value
    if params.area_name:
        query.update(area_filter(params.area_name))
    query.update(region_filter(params.division, params.district, params.upazila))
    return query


async def _load_sale_out(listing_id: str | ObjectId) -> SaleListingOut:
    return sale_listing_to_out(await load_listing_doc(listing_id, SALE_ONLY))


@router.get("/sale-listings", response_model=SaleSearchResult)
@router.get("/search", response_model=SaleSearchResult)
async def search_sale_listings(params: Annotated[SaleSearchParams, Query()]):
    """Search sales, limited to the buyer's target area the same way as the rental search."""
    center = resolve_center(params.landmark, params.lat, params.lng)
    sort = params.sort or (SaleSort.DISTANCE if center else SaleSort.NEWEST)
    docs, total = await search_target_area(_sale_filter(params), center, params.radius_km, _SALE_SORTS[sort], params.limit)
    return SaleSearchResult(
        items=[sale_listing_to_out(doc) for doc in docs],
        total=total,
        area_name=params.area_name,
        center=center,
        radius_km=params.radius_km if center else None,
    )


@router.get("/sale-listings/mine", response_model=list[SaleListingOut])
async def my_sale_listings(user: dict = Depends(require_roles(Role.OWNER))):
    pipeline = [{"$match": {"lister_id": user["_id"], **SALE_ONLY}}, {"$sort": {"created_at": -1}}, *LISTER_LOOKUP]
    return [sale_listing_to_out(doc) for doc in await get_db().listings.aggregate(pipeline).to_list(None)]


@router.get("/sale-listings/{listing_id}", response_model=SaleListingOut)
async def get_sale_listing(listing_id: str):
    return await _load_sale_out(listing_id)


@router.post("/sale-listings", response_model=SaleListingOut, status_code=status.HTTP_201_CREATED)
async def create_sale_listing(payload: SaleListingIn, user: dict = Depends(require_roles(Role.OWNER))):
    now = _now()
    listing = {
        **sale_listing_fields(payload),
        "sale_status": SaleStatus.AVAILABLE.value,
        "title_status": TitleStatus.NOT_SUBMITTED.value,
        "title_documents": [],
        "title_review_note": None,
        "lister_id": user["_id"],
        "created_at": now,
        "updated_at": now,
    }
    await get_db().listings.insert_one(listing)
    return await _load_sale_out(listing["_id"])


@router.put("/sale-listings/{listing_id}", response_model=SaleListingOut)
async def update_sale_listing(
    listing_id: str, payload: SaleListingIn, user: dict = Depends(require_roles(Role.OWNER))
):
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    await get_db().listings.update_one(
        {"_id": listing["_id"], "lister_id": user["_id"]}, {"$set": {**sale_listing_fields(payload), "updated_at": _now()}}
    )
    return await _load_sale_out(listing["_id"])


@router.delete("/sale-listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sale_listing(listing_id: str, user: dict = Depends(get_current_user)):
    if user["role"] == Role.ADMIN:
        listing = await get_db().listings.find_one({"_id": parse_object_id(listing_id), **SALE_ONLY})
        if listing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    else:
        listing = await load_own_listing(listing_id, user, SALE_ONLY)
    owner_filter = {} if user["role"] == Role.ADMIN else {"lister_id": user["_id"]}
    await delete_listing_with_deals(listing, owner_filter, by_admin=user["role"] == Role.ADMIN)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- listing photos (the first one is the cover)


@router.post("/sale-listings/{listing_id}/photos", response_model=SaleListingOut)
@limiter.limit(PHOTO_UPLOAD_LIMIT, key_func=user_or_ip)
async def upload_sale_photos(
    request: Request,
    listing_id: str,
    files: Annotated[list[UploadFile], File(description="JPEG, PNG or WebP, up to 5 MB each")],
    user: dict = Depends(require_roles(Role.OWNER)),
):
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    await add_listing_photos(listing, {"lister_id": user["_id"]}, files)
    return await _load_sale_out(listing["_id"])


@router.delete("/sale-listings/{listing_id}/photos/{photo_id}", response_model=SaleListingOut)
async def delete_sale_photo(
    listing_id: str, photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)], user: dict = Depends(require_roles(Role.OWNER))
):
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    await remove_listing_photo(listing, {"lister_id": user["_id"]}, photo_id)
    return await _load_sale_out(listing["_id"])


@router.post("/sale-listings/{listing_id}/photos/{photo_id}/cover", response_model=SaleListingOut)
async def make_sale_cover(
    listing_id: str, photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)], user: dict = Depends(require_roles(Role.OWNER))
):
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    await make_cover_photo(listing, {"lister_id": user["_id"]}, photo_id)
    return await _load_sale_out(listing["_id"])


@router.get("/sale-listings/{listing_id}/photos/{photo_id}")
async def get_sale_photo(
    listing_id: str,
    photo_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)],
    size: Annotated[Literal["full", "thumb"], Query()] = "full",
):
    """Public, like the listing itself."""
    listing = await load_listing_doc(listing_id, SALE_ONLY, with_lister=False)
    return listing_photo_response(listing, photo_id, thumbnail=size == "thumb")


@router.post("/sale-listings/{listing_id}/video", response_model=SaleListingOut)
@limiter.limit(VIDEO_UPLOAD_LIMIT, key_func=user_or_ip)
async def upload_sale_video(
    request: Request,
    listing_id: str,
    file: Annotated[UploadFile, File(description="MP4 or MOV, up to 100 MB and 3 minutes")],
    user: dict = Depends(require_roles(Role.OWNER)),
):
    """Replaces the listing's video if it already has one."""
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    await set_listing_video(listing, {"lister_id": user["_id"]}, file)
    return await _load_sale_out(listing["_id"])


@router.delete("/sale-listings/{listing_id}/video/{video_id}", response_model=SaleListingOut)
async def delete_sale_video(
    listing_id: str, video_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)], user: dict = Depends(require_roles(Role.OWNER))
):
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    await remove_listing_video(listing, {"lister_id": user["_id"]}, video_id)
    return await _load_sale_out(listing["_id"])


@router.get("/sale-listings/{listing_id}/video/{video_id}")
async def get_sale_video(listing_id: str, video_id: Annotated[str, Path(pattern=PHOTO_ID_PATTERN)]):
    """Public, like the photos."""
    listing = await load_listing_doc(listing_id, SALE_ONLY, with_lister=False)
    return listing_video_response(listing, video_id)


# ================================================================ Feature 7: title vault


async def _load_vault_listing(listing_id: str, user: dict) -> dict:
    """Title deeds are visible to the seller, admins, and buyers actively negotiating (an open or accepted offer)."""
    listing = await get_db().listings.find_one({"_id": parse_object_id(listing_id), **SALE_ONLY})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if listing["lister_id"] == user["_id"] or user["role"] == Role.ADMIN:
        return listing
    negotiating = await get_db().offers.find_one(
        {
            "listing_id": listing["_id"],
            "buyer_id": user["_id"],
            "status": {"$in": [*[s.value for s in OPEN_OFFER_STATUSES], OfferStatus.ACCEPTED.value]},
        },
        {"_id": 1},
    )
    if negotiating is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Title documents are shared with the seller, admins and buyers with an open offer"
        )
    return listing


def _vault_out(listing: dict) -> TitleVaultOut:
    documents = listing.get("title_documents", [])
    on_file = {d["doc_type"] for d in documents}
    return TitleVaultOut(
        listing_id=str(listing["_id"]),
        title_status=listing["title_status"],
        title_review_note=listing.get("title_review_note"),
        documents=documents,
        missing=[t for t in TitleDocType if t.value not in on_file],
    )


@router.get("/sale-listings/{listing_id}/title-documents", response_model=TitleVaultOut)
async def get_title_vault(listing_id: str, user: dict = Depends(get_current_user)):
    return _vault_out(await _load_vault_listing(listing_id, user))


@router.post("/sale-listings/{listing_id}/title-documents", response_model=TitleVaultOut)
@limiter.limit(SENSITIVE_UPLOAD_LIMIT, key_func=user_or_ip)
async def upload_title_document(
    request: Request,
    listing_id: str,
    doc_type: Annotated[TitleDocType, Form()],
    file: Annotated[UploadFile, File()],
    user: dict = Depends(require_roles(Role.OWNER)),
):
    listing = await load_own_listing(listing_id, user, SALE_ONLY)
    stored = await store_upload(file, settings.upload_dir / "title" / str(listing["_id"]), DOCUMENT_TYPES)
    now = _now()
    # One file per document type; any upload re-opens admin review and hides the badge until then.
    documents = [d for d in listing.get("title_documents", []) if d["doc_type"] != doc_type.value]
    documents.append({"doc_type": doc_type.value, **stored, "uploaded_at": now})
    updated = await get_db().listings.find_one_and_update(
        {"_id": listing["_id"], "lister_id": user["_id"]},
        {
            "$set": {
                "title_documents": documents,
                "title_status": TitleStatus.PENDING.value,
                "title_review_note": None,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return _vault_out(updated)


@router.get("/sale-listings/{listing_id}/title-documents/{doc_type}/file")
async def download_title_document(listing_id: str, doc_type: TitleDocType, user: dict = Depends(get_current_user)):
    listing = await _load_vault_listing(listing_id, user)
    document = next((d for d in listing.get("title_documents", []) if d["doc_type"] == doc_type.value), None)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return private_file_response(document)


@router.get("/title-reviews/pending", response_model=list[SaleListingOut])
async def list_pending_title_reviews(_admin: dict = Depends(require_roles(Role.ADMIN))):
    pipeline = [
        {"$match": {**SALE_ONLY, "title_status": TitleStatus.PENDING.value}},
        {"$sort": {"updated_at": 1}},
        *LISTER_LOOKUP,
    ]
    return [sale_listing_to_out(doc) for doc in await get_db().listings.aggregate(pipeline).to_list(200)]


@router.patch("/sale-listings/{listing_id}/title-review", response_model=TitleVaultOut)
async def review_title(
    listing_id: str, payload: TitleReviewRequest, _admin: dict = Depends(require_roles(Role.ADMIN))
):
    updated = await get_db().listings.find_one_and_update(
        {"_id": parse_object_id(listing_id), **SALE_ONLY, "title_status": TitleStatus.PENDING.value},
        {"$set": {"title_status": payload.status.value, "title_review_note": payload.note, "updated_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No title documents awaiting review for this listing")
    return _vault_out(updated)


# ================================================================ Feature 8: price-per-sqft analysis

_ANALYSIS_RADII_KM = (2, 5, 10)
_MIN_COMPARABLES = 3
_MARKET_BAND_PCT = 5


@router.get("/sale-listings/{listing_id}/price-analysis", response_model=PriceAnalysis)
async def price_analysis(listing_id: str):
    listing = await load_listing_doc(listing_id, SALE_ONLY, with_lister=False)
    comps: list[dict] = []
    radius = _ANALYSIS_RADII_KM[0]
    # Widen the neighbourhood until there are enough comparable sales of the same property type.
    for radius in _ANALYSIS_RADII_KM:
        pipeline = [
            {
                "$geoNear": {
                    "near": listing["location"]["geo"],
                    "key": GEO_KEY,
                    "distanceField": "distance_m",
                    "maxDistance": radius * 1000,
                    "spherical": True,
                    "query": {**SALE_ONLY, "property_type": listing["property_type"], "_id": {"$ne": listing["_id"]}},
                }
            },
            {"$project": {"title": 1, "location.area_name": 1, "location.sub_area": 1, "price_per_sqft": 1, "distance_m": 1}},
        ]
        comps = await get_db().listings.aggregate(pipeline).to_list(None)
        if len(comps) >= _MIN_COMPARABLES:
            break

    ppsf = listing["price_per_sqft"]
    neighborhood = difference = None
    verdict = "NOT_ENOUGH_DATA"
    if comps:
        values = [c["price_per_sqft"] for c in comps]
        average = round(statistics.fmean(values))
        neighborhood = NeighborhoodStats(
            radius_km=radius,
            count=len(values),
            average_ppsf=average,
            median_ppsf=round(statistics.median(values)),
            min_ppsf=min(values),
            max_ppsf=max(values),
        )
        difference = round((ppsf - average) / average * 100, 1)
        if len(comps) >= _MIN_COMPARABLES:
            verdict = (
                "BELOW_MARKET" if difference < -_MARKET_BAND_PCT
                else "ABOVE_MARKET" if difference > _MARKET_BAND_PCT
                else "AT_MARKET"
            )
    return PriceAnalysis(
        listing_id=str(listing["_id"]),
        asking_price=listing["sale"]["asking_price"],
        size_sqft=listing["building"]["size_sqft"],
        price_per_sqft=ppsf,
        neighborhood=neighborhood,
        difference_pct=difference,
        verdict=verdict,
        comparables=[
            Comparable(
                id=str(c["_id"]),
                title=c["title"],
                area=area_label(c["location"]),
                price_per_sqft=c["price_per_sqft"],
                distance_km=round(c["distance_m"] / 1000, 2),
            )
            for c in comps[:5]
        ],
    )


# ================================================================ Feature 9: offers


def _offer_out(doc: dict) -> OfferOut:
    return OfferOut.model_validate(serialize_doc(doc))


async def _close_open_offers(listing_id: ObjectId, note: str, except_id: ObjectId | None = None) -> None:
    query: dict = {"listing_id": listing_id, "is_open": True}
    if except_id is not None:
        query["_id"] = {"$ne": except_id}
    now = _now()
    closing = [doc["_id"] for doc in await get_db().offers.find(query, {"_id": 1}).to_list(None)]
    await get_db().offers.update_many(
        {**query, "_id": {"$in": closing}},
        {
            "$set": {"status": OfferStatus.CLOSED.value, "is_open": False, "updated_at": now},
            "$push": {"history": {"at": now, "actor": "SYSTEM", "event": OfferEventType.CLOSED.value, "note": note}},
        },
    )
    for offer in await get_db().offers.find({"_id": {"$in": closing}, "status": OfferStatus.CLOSED.value}).to_list(None):
        await chat_cards.offer_changed(offer, None)


def _offer_parties(user: dict) -> dict:
    return {"$or": [{"buyer_id": user["_id"]}, {"seller_id": user["_id"]}]}


async def _load_offer_for_party(offer_id: str, user: dict) -> dict:
    offer = await get_db().offers.find_one({"_id": parse_object_id(offer_id), **_offer_parties(user)})
    if offer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    return offer


@router.post("/offers", response_model=OfferOut, status_code=status.HTTP_201_CREATED)
async def create_offer(payload: OfferCreate, user: dict = Depends(require_roles(Role.BUYER))):
    listing = await get_db().listings.find_one({"_id": parse_object_id(payload.listing_id), **SALE_ONLY})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if listing.get("sale_status") != SaleStatus.AVAILABLE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "The seller has already accepted an offer on this property")
    seller = await get_db().users.find_one({"_id": listing["lister_id"]}, {"full_name": 1})
    now = _now()
    # Names and listing details are snapshotted so the ledger reads the same even if they change later.
    offer = {
        "listing_id": listing["_id"],
        "listing_title": listing["title"],
        "asking_price": listing["sale"]["asking_price"],
        "buyer_id": user["_id"],
        "seller_id": listing["lister_id"],
        "buyer": {"id": user["_id"], "full_name": user["full_name"]},
        "seller": {"id": listing["lister_id"], "full_name": seller["full_name"] if seller else "Seller"},
        "offer_type": payload.offer_type.value,
        "status": OfferStatus.AWAITING_SELLER.value,
        "is_open": True,
        "amount": payload.amount,
        "token_amount": payload.token_amount,
        "history": [
            {
                "at": now,
                "actor": "BUYER",
                "event": OfferEventType.OFFERED.value,
                "amount": payload.amount,
                "token_amount": payload.token_amount,
                "note": payload.note,
            }
        ],
        "created_at": now,
        "updated_at": now,
    }
    try:
        await get_db().offers.insert_one(offer)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have an open offer on this property")
    await chat_cards.offer_made(offer, user)
    return _offer_out(offer)


@router.get("/offers/mine", response_model=list[OfferOut])
async def my_offers(
    side: Annotated[str | None, Query(pattern="^(buyer|seller)$")] = None,
    user: dict = Depends(get_current_user),
):
    if side == "buyer":
        query = {"buyer_id": user["_id"]}
    elif side == "seller":
        query = {"seller_id": user["_id"]}
    else:
        query = {"$or": [{"buyer_id": user["_id"]}, {"seller_id": user["_id"]}]}
    docs = await get_db().offers.find(query).sort("updated_at", -1).to_list(200)
    return [_offer_out(doc) for doc in docs]


@router.get("/offers/{offer_id}", response_model=OfferOut)
async def get_offer(offer_id: str, user: dict = Depends(get_current_user)):
    return _offer_out(await _load_offer_for_party(offer_id, user))


@router.post("/offers/{offer_id}/respond", response_model=OfferOut)
async def respond_to_offer(offer_id: str, payload: OfferResponse, user: dict = Depends(get_current_user)):
    offer = await _load_offer_for_party(offer_id, user)
    actor = "BUYER" if offer["buyer_id"] == user["_id"] else "SELLER"
    current = offer["status"]
    if current not in OPEN_OFFER_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This offer is already closed")

    changes: dict = {}
    if payload.action == "WITHDRAW":
        if actor != "BUYER":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the buyer can withdraw an offer")
        new_status, event = OfferStatus.WITHDRAWN, OfferEventType.WITHDRAWN
    else:
        turn = "SELLER" if current == OfferStatus.AWAITING_SELLER else "BUYER"
        if actor != turn:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Waiting for the {turn.lower()} to respond")
        if payload.action == "ACCEPT":
            new_status, event = OfferStatus.ACCEPTED, OfferEventType.ACCEPTED
        elif payload.action == "REJECT":
            new_status, event = OfferStatus.REJECTED, OfferEventType.REJECTED
        else:
            token = payload.token_amount if payload.token_amount is not None else offer.get("token_amount")
            try:
                check_token_amount(OfferType(offer["offer_type"]), payload.amount, token)
            except ValueError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
            changes = {"amount": payload.amount, "token_amount": token}
            new_status = OfferStatus.AWAITING_BUYER if actor == "SELLER" else OfferStatus.AWAITING_SELLER
            event = OfferEventType.COUNTERED

    # Accepting takes the property off the market first, so two offers can never both be accepted. Either side may
    # accept (the buyer accepts a counter-offer), so the lock is tied to the offer's seller, not the acting user.
    if new_status == OfferStatus.ACCEPTED:
        locked = await get_db().listings.update_one(
            {"_id": offer["listing_id"], "lister_id": offer["seller_id"], "sale_status": SaleStatus.AVAILABLE.value, "suspended": {"$ne": True}},
            {"$set": {"sale_status": SaleStatus.UNDER_OFFER.value, "updated_at": _now()}},
        )
        if locked.matched_count == 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "Another offer on this property was already accepted")

    now = _now()
    history_entry = {
        "at": now,
        "actor": actor,
        "event": event.value,
        "amount": changes.get("amount", offer["amount"]),
        "token_amount": changes.get("token_amount", offer.get("token_amount")),
        "note": payload.note,
    }
    updated = await get_db().offers.find_one_and_update(
        # Matching on the status we read makes each transition atomic against concurrent responses, and the
        # party field keeps the write tied to the user it was checked for.
        {"_id": offer["_id"], "status": current, ("buyer_id" if actor == "BUYER" else "seller_id"): user["_id"]},
        {
            "$set": {
                **changes,
                "status": new_status.value,
                "is_open": new_status in OPEN_OFFER_STATUSES,
                "updated_at": now,
            },
            "$push": {"history": history_entry},
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        if new_status == OfferStatus.ACCEPTED:
            await get_db().listings.update_one(
                {"_id": offer["listing_id"]}, {"$set": {"sale_status": SaleStatus.AVAILABLE.value}}
            )
        raise HTTPException(status.HTTP_409_CONFLICT, "The offer changed while you were responding. Reload it.")
    await chat_cards.offer_changed(updated, user)
    if new_status == OfferStatus.ACCEPTED:
        await _close_open_offers(offer["listing_id"], "The seller accepted another offer", except_id=offer["_id"])
    return _offer_out(updated)


# ================================================================ Feature 10: visit slots


def _visit_out(doc: dict) -> VisitOut:
    return VisitOut.model_validate(serialize_doc(doc))


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, VISIT_DAY_START_HOUR, tzinfo=DHAKA_TZ)
    end = datetime(day.year, day.month, day.day, VISIT_DAY_END_HOUR, tzinfo=DHAKA_TZ)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("/listings/{listing_id}/visit-slots", response_model=DaySlots)
async def visit_slots_for_day(
    listing_id: str,
    day: Annotated[date | None, Query(alias="date")] = None,
    user: dict | None = Depends(get_optional_user),
):
    listing = await get_db().listings.find_one({"_id": parse_object_id(listing_id), "suspended": {"$ne": True}}, {"lister_id": 1})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    today = _now().astimezone(DHAKA_TZ).date()
    day = day or today
    if not today <= day <= today + timedelta(days=VISIT_BOOKING_WINDOW_DAYS):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Pick a date within the next {VISIT_BOOKING_WINDOW_DAYS} days"
        )

    start, end = _day_bounds(day)
    busy_query: dict = {"status": VisitStatus.BOOKED.value, "starts_at": {"$gte": start, "$lt": end}}
    # The host is busy across all of their listings, not just this one.
    host_busy = {
        v["starts_at"]
        for v in await get_db().visit_slots.find({**busy_query, "host_id": listing["lister_id"]}, {"starts_at": 1}).to_list(None)
    }
    mine = set()
    if user is not None:
        mine = {
            v["starts_at"]
            for v in await get_db().visit_slots.find({**busy_query, "visitor_id": user["_id"]}, {"starts_at": 1}).to_list(None)
        }

    now = _now()
    slots, cursor = [], start
    while cursor < end:
        reason = "PAST" if cursor <= now else "YOURS" if cursor in mine else "TAKEN" if cursor in host_busy else None
        slots.append(
            SlotOut(starts_at=cursor, ends_at=cursor + timedelta(minutes=SLOT_MINUTES), available=reason is None, reason=reason)
        )
        cursor += timedelta(minutes=SLOT_MINUTES)
    return DaySlots(listing_id=listing_id, date=day, slots=slots)


@router.post("/visits", response_model=VisitOut, status_code=status.HTTP_201_CREATED)
async def book_visit(payload: VisitCreate, user: dict = Depends(require_roles(*VISITOR_ROLES))):
    listing = await get_db().listings.find_one({"_id": parse_object_id(payload.listing_id), "suspended": {"$ne": True}})
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    if listing["lister_id"] == user["_id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't book a visit to your own listing")
    if listing.get("rental_status") == RentalStatus.RENTED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "This place has already been rented")
    now = _now()
    if payload.starts_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That time has already passed")
    if payload.starts_at > now + timedelta(days=VISIT_BOOKING_WINDOW_DAYS + 1):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Visits can be booked up to {VISIT_BOOKING_WINDOW_DAYS} days ahead"
        )
    host = await get_db().users.find_one({"_id": listing["lister_id"]})
    visit = {
        "listing_id": listing["_id"],
        "listing_title": listing["title"],
        "listing_mode": listing.get("listing_mode", "RENT"),
        "host_id": listing["lister_id"],
        "visitor_id": user["_id"],
        "host": _party(host) if host else {"id": listing["lister_id"], "full_name": "Lister", "phone": ""},
        "visitor": _party(user),
        "starts_at": payload.starts_at,
        "ends_at": payload.starts_at + timedelta(minutes=SLOT_MINUTES),
        "mode": payload.mode.value,
        "status": VisitStatus.BOOKED.value,
        "approval": VisitApproval.PENDING.value,
        "note": payload.note,
        "cancelled_by": None,
        "created_at": now,
    }
    try:
        # Unique partial indexes on (host_id, starts_at) and (visitor_id, starts_at) for BOOKED visits
        # make conflict detection atomic: two people racing for one slot can't both get it.
        await get_db().visit_slots.insert_one(visit)
    except DuplicateKeyError as exc:
        if "visitor_id" in (exc.details or {}).get("keyPattern", {}):
            raise HTTPException(status.HTTP_409_CONFLICT, "You already have a visit booked at that time")
        raise HTTPException(status.HTTP_409_CONFLICT, "That slot is already taken. Pick another time.")
    # The lister is alerted (live, or on their next connection) and the request appears in their chat with the visitor.
    await chat_cards.visit_booked(visit, user)
    return _visit_out(visit)


@router.get("/visits/mine", response_model=list[VisitOut])
async def my_visits(
    include_past: bool = False,
    user: dict = Depends(get_current_user),
):
    query: dict = {"$or": [{"visitor_id": user["_id"]}, {"host_id": user["_id"]}]}
    if not include_past:
        query["ends_at"] = {"$gte": _now()}
    docs = await get_db().visit_slots.find(query).sort("starts_at", 1).to_list(200)
    return [_visit_out(doc) for doc in docs]


@router.post("/visits/{visit_id}/cancel", response_model=VisitOut)
async def cancel_visit(visit_id: str, user: dict = Depends(get_current_user)):
    parties = {"$or": [{"host_id": user["_id"]}, {"visitor_id": user["_id"]}]}
    visit = await get_db().visit_slots.find_one({"_id": parse_object_id(visit_id), **parties})
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    updated = await get_db().visit_slots.find_one_and_update(
        {"_id": visit["_id"], **parties, "status": VisitStatus.BOOKED.value, "starts_at": {"$gt": _now()}},
        {
            "$set": {
                "status": VisitStatus.CANCELLED.value,
                "cancelled_by": "HOST" if user["_id"] == visit["host_id"] else "VISITOR",
                "cancelled_at": _now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only upcoming booked visits can be cancelled")
    await chat_cards.visit_changed(updated, user)
    return _visit_out(updated)


@router.patch("/visits/{visit_id}/status", response_model=VisitOut)
async def update_visit_status(visit_id: str, payload: VisitStatusUpdate, user: dict = Depends(get_current_user)):
    """The host approves a visit, proposes a new time or declines it (the chat card's buttons). The visitor's only
    move here is APPROVED, to accept a time the host proposed; to call a visit off they cancel it."""
    visit = await get_db().visit_slots.find_one(
        {"_id": parse_object_id(visit_id), "$or": [{"host_id": user["_id"]}, {"visitor_id": user["_id"]}]}
    )
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    now = _now()
    if visit["status"] != VisitStatus.BOOKED or visit["starts_at"] <= now:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only upcoming booked visits can be changed")
    is_host = visit["host_id"] == user["_id"]
    current = visit.get("approval") or VisitApproval.PENDING.value

    if not is_host and (payload.status != VisitApproval.APPROVED or current != VisitApproval.RESCHEDULE_PROPOSED):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the host can approve, reschedule or decline a visit")
    if payload.status == VisitApproval.APPROVED:
        if is_host and current != VisitApproval.PENDING:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Waiting for the visitor to accept the new time" if current == VisitApproval.RESCHEDULE_PROPOSED
                else "This visit is already approved",
            )
        changes: dict = {"approval": VisitApproval.APPROVED.value}
    elif payload.status == VisitApproval.RESCHEDULE_PROPOSED:
        new_start = payload.starts_at
        if new_start <= now:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That time has already passed")
        if new_start > now + timedelta(days=VISIT_BOOKING_WINDOW_DAYS + 1):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Visits can be booked up to {VISIT_BOOKING_WINDOW_DAYS} days ahead")
        if new_start == visit["starts_at"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick a different time from the one booked")
        changes = {
            "approval": VisitApproval.RESCHEDULE_PROPOSED.value,
            "starts_at": new_start,
            "ends_at": new_start + timedelta(minutes=SLOT_MINUTES),
            "original_starts_at": visit.get("original_starts_at") or visit["starts_at"],
        }
    else:
        changes = {
            "approval": VisitApproval.DECLINED.value,
            "status": VisitStatus.CANCELLED.value,
            "cancelled_by": "HOST",
            "cancelled_at": now,
        }

    # Matching on the state we read keeps each answer atomic, and the party field ties the write to this user.
    approval_filter = {"$in": [None, current]} if current == VisitApproval.PENDING else current
    try:
        updated = await get_db().visit_slots.find_one_and_update(
            {
                "_id": visit["_id"],
                ("host_id" if is_host else "visitor_id"): user["_id"],
                "status": VisitStatus.BOOKED.value,
                "approval": approval_filter,
                "starts_at": visit["starts_at"],
            },
            {"$set": changes},
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError as exc:
        if "visitor_id" in (exc.details or {}).get("keyPattern", {}):
            raise HTTPException(status.HTTP_409_CONFLICT, "The visitor already has another visit booked at that time")
        raise HTTPException(status.HTTP_409_CONFLICT, "You already have a visit booked at that time. Pick another.")
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The visit changed while you were answering. Reload it.")
    await chat_cards.visit_changed(updated, user)
    return _visit_out(updated)
