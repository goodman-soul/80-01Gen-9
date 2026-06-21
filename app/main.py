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


@app.get("/")
async def root(request: Request, db=Depends(get_db)):
    current_user = await get_current_user(request, db)
    
    batches = db.execute("""
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
    """).fetchall()
    
    batch_list = []
    for b in batches:
        progress = int((b[6] / b[5]) * 100) if b[5] > 0 else 0
        batch_list.append({
            "id": b[0],
            "name": b[1],
            "description": b[2],
            "price": b[3],
            "unit": b[4],
            "total_quantity": b[5],
            "adopted_quantity": b[6],
            "harvest_date": str(b[7]) if b[7] else "",
            "status": b[8],
            "plot_name": b[9],
            "plot_type": b[10],
            "plot_location": b[11],
            "farmer_name": b[12],
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
