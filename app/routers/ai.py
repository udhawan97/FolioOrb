"""
app/routers/ai.py
AI-powered summary endpoints using Claude.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.ai_service import generate_stock_summary, generate_portfolio_insight
from app.services.stock_service import get_stock_data, get_all_quotes, DEFAULT_HOLDINGS
from app.models import AISummary
from datetime import datetime
 
router = APIRouter(prefix="/api/ai", tags=["ai"])
 
 
@router.get("/summary/{ticker}")
async def get_stock_summary(
    ticker: str,
    force_refresh: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get AI summary for a single ticker.
    Checks the database cache first — only calls Claude if needed.
    Use force_refresh=true to always generate a fresh summary.
    """
    ticker = ticker.upper()
 
    # Check cache — do we have a recent summary for this ticker?
    if not force_refresh:
        cached = (
            db.query(AISummary)
            .filter(
                AISummary.ticker == ticker,
                AISummary.summary_type == "stock"
            )
            .order_by(AISummary.generated_at.desc())
            .first()
        )
        if cached:
            return {
                "ticker": ticker,
                "summary": cached.summary_text,
                "generated_at": cached.generated_at.isoformat(),
                "from_cache": True,
                "price_when_generated": cached.price_when_generated,
            }
 
    # Cache miss or force_refresh — fetch live data and call Claude
    stock_data = get_stock_data(ticker)
    if stock_data.get("error"):
        raise HTTPException(status_code=404, detail=f"Cannot fetch data for {ticker}")
 
    # Generate the AI summary
    summary_text = generate_stock_summary(stock_data)
 
    # Save to cache
    summary = AISummary(
        ticker=ticker,
        summary_type="stock",
        summary_text=summary_text,
        price_when_generated=stock_data["current_price"],
        model_used="claude-3-haiku-20240307",
    )
    db.add(summary)
    db.commit()
 
    return {
        "ticker": ticker,
        "summary": summary_text,
        "generated_at": datetime.utcnow().isoformat(),
        "from_cache": False,
        "price_when_generated": stock_data["current_price"],
    }
 
 
@router.get("/summaries/all")
async def get_all_summaries(db: Session = Depends(get_db)):
    """
    Get or generate summaries for all default holdings.
    Returns cached summaries immediately, generates new ones for missing tickers.
    This endpoint may take 30-60 seconds if generating all 10 summaries fresh.
    """
    results = {}
 
    # Fetch all live prices once
    quotes = {q["ticker"]: q for q in get_all_quotes()}
 
    for ticker in DEFAULT_HOLDINGS:
        # Check cache
        cached = (
            db.query(AISummary)
            .filter(AISummary.ticker == ticker, AISummary.summary_type == "stock")
            .order_by(AISummary.generated_at.desc())
            .first()
        )
 
        if cached:
            results[ticker] = {"summary": cached.summary_text, "from_cache": True}
        else:
            # Generate fresh summary
            stock_data = quotes.get(ticker, {})
            if stock_data and not stock_data.get("error"):
                summary_text = generate_stock_summary(stock_data)
                new_summary = AISummary(
                    ticker=ticker, summary_type="stock",
                    summary_text=summary_text,
                    price_when_generated=stock_data["current_price"],
                    model_used="claude-3-haiku-20240307",
                )
                db.add(new_summary)
                db.commit()
                results[ticker] = {"summary": summary_text, "from_cache": False}
 
    return {"summaries": results, "count": len(results)}
