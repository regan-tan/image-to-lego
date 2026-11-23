from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.api.dependencies import CurrentOwnerId
from app.core.database import DatabaseSession, set_database_owner

router = APIRouter(tags=["credits"])


class CreditTransactionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    kind: Literal["starter_grant", "job_charge", "job_refund", "admin_grant"]
    amount: int
    balance_after: int = Field(serialization_alias="balanceAfter")
    created_at: datetime = Field(serialization_alias="createdAt")


class CreditsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    balance: int
    reconstruction_cost: int = Field(serialization_alias="reconstructionCost")
    conversion_cost: int = Field(serialization_alias="conversionCost")
    transactions: list[CreditTransactionResponse]


@router.get("/credits", response_model=CreditsResponse)
async def get_credits(
    owner_id: CurrentOwnerId,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CreditsResponse:
    # This write only establishes the one-time starter grant under the account row lock.
    async with session.begin():
        await set_database_owner(session, owner_id)
        balance = await session.scalar(
            text("select public.credit_ensure_account(:owner_id)"),
            {"owner_id": owner_id},
        )
        rows = await session.execute(
            text("""
                select id, kind, amount, balance_after, created_at
                from public.credit_transactions
                where owner_id = :owner_id
                order by created_at desc, id desc
                limit :limit
                offset :offset
            """),
            {"owner_id": owner_id, "limit": limit, "offset": offset},
        )
        policy = (
            await session.execute(
                text("select reconstruction_cost, conversion_cost from public.credit_policy")
            )
        ).mappings().one()
    return CreditsResponse(
        balance=int(balance),
        reconstruction_cost=int(policy["reconstruction_cost"]),
        conversion_cost=int(policy["conversion_cost"]),
        transactions=[CreditTransactionResponse.model_validate(row) for row in rows.mappings()],
    )
