from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
import os

from app.database import init_db, get_db
from app.routers import auth, farmer, consumer, admin as admin_router
from app.utils.auth import get_current_user
from app.utils.templates import TemplateResponse

app = FastAPI(title="农产品预售采摘认养平台")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.on_event("startup")
def startup_event():
    init_db()


def fetch_all_dicts(cursor):
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


@app.get("/")
async def root(request: Request, db=Depends(get_db)):
    current_user = await get_current_user(request, db)
    
    cursor = db.execute("""
        SELECT b.id, b.name, b.description, b.price, b.unit, b.total_quantity,
               b.adopted_quantity, b.harvest_date, b.status,
               p.name as plot_name, p.type as plot_type, p.location as plot_location,
               u.full_name as farmer_name
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        WHERE b.status = 'open'
        ORDER BY b.created_at DESC
        LIMIT 8
    """)
    batches = fetch_all_dicts(cursor)
    
    batch_list = []
    for b in batches:
        progress = int((b["adopted_quantity"] / b["total_quantity"]) * 100) if b["total_quantity"] > 0 else 0
        batch_list.append({
            "id": b["id"],
            "name": b["name"],
            "description": b["description"],
            "price": b["price"],
            "unit": b["unit"],
            "total_quantity": b["total_quantity"],
            "adopted_quantity": b["adopted_quantity"],
            "harvest_date": str(b["harvest_date"]) if b["harvest_date"] else "",
            "status": b["status"],
            "plot_name": b["plot_name"],
            "plot_type": b["plot_type"],
            "plot_location": b["plot_location"],
            "farmer_name": b["farmer_name"],
            "progress": progress
        })
    
    return TemplateResponse("index.html", {
        "request": request,
        "current_user": current_user,
        "batches": batch_list
    })


app.include_router(auth.router, prefix="/auth", tags=["认证"])
app.include_router(farmer.router, prefix="/farmer", tags=["农户端"])
app.include_router(consumer.router, prefix="/consumer", tags=["消费者端"])
app.include_router(admin_router.router, prefix="/admin", tags=["管理端"])
