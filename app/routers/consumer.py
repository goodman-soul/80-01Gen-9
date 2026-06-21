from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional
import duckdb

from app.database import get_db
from app.utils.auth import get_current_user
from app.utils.templates import TemplateResponse

router = APIRouter()


@router.get("/batches", response_class=HTMLResponse)
async def batch_list(
    request: Request,
    type_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    
    query = """
        SELECT b.id, b.name, b.description, b.price, b.unit, b.total_quantity,
               b.adopted_quantity, b.harvest_date, b.delivery_methods, b.status,
               p.name as plot_name, p.type as plot_type, p.location as plot_location,
               u.full_name as farmer_name
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        WHERE b.status = 'open'
    """
    params = []
    
    if type_filter:
        query += " AND p.type = ?"
        params.append(type_filter)
    
    query += " ORDER BY b.created_at DESC"
    
    batches = db.execute(query, params).fetchall()
    
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
            "delivery_methods": b[8].split(",") if b[8] else [],
            "status": b[9],
            "plot_name": b[10],
            "plot_type": b[11],
            "plot_location": b[12],
            "farmer_name": b[13],
            "progress": progress,
            "remaining": b[5] - b[6]
        })
    
    return TemplateResponse("consumer/batches.html", {
        "request": request,
        "current_user": current_user,
        "batches": batch_list,
        "type_filter": type_filter
    })


@router.get("/batches/{batch_id}", response_class=HTMLResponse)
async def batch_detail(
    request: Request,
    batch_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    
    batch = db.execute("""
        SELECT b.id, b.name, b.description, b.price, b.unit, b.total_quantity,
               b.adopted_quantity, b.harvest_date, b.delivery_methods, b.status, b.created_at,
               p.name as plot_name, p.type as plot_type, p.location as plot_location,
               p.description as plot_description, p.area,
               u.full_name as farmer_name, u.id as farmer_id
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        WHERE b.id = ?
    """, [batch_id]).fetchone()
    
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    progress = int((batch[6] / batch[5]) * 100) if batch[5] > 0 else 0
    
    batch_dict = {
        "id": batch[0],
        "name": batch[1],
        "description": batch[2],
        "price": batch[3],
        "unit": batch[4],
        "total_quantity": batch[5],
        "adopted_quantity": batch[6],
        "harvest_date": str(batch[7]) if batch[7] else "",
        "delivery_methods": batch[8].split(",") if batch[8] else [],
        "status": batch[9],
        "created_at": str(batch[10]),
        "plot_name": batch[11],
        "plot_type": batch[12],
        "plot_location": batch[13],
        "plot_description": batch[14],
        "plot_area": batch[15],
        "farmer_name": batch[16],
        "farmer_id": batch[17],
        "progress": progress,
        "remaining": batch[5] - batch[6]
    }
    
    weather_events = db.execute("""
        SELECT id, event_type, description, severity, affected_date, created_at
        FROM weather_events
        WHERE batch_id = ?
        ORDER BY created_at DESC
    """, [batch_id]).fetchall()
    
    event_list = []
    for w in weather_events:
        event_list.append({
            "id": w[0],
            "event_type": w[1],
            "description": w[2],
            "severity": w[3],
            "affected_date": str(w[4]) if w[4] else "",
            "created_at": str(w[5])
        })
    
    return TemplateResponse("consumer/batch_detail.html", {
        "request": request,
        "current_user": current_user,
        "batch": batch_dict,
        "weather_events": event_list
    })


@router.post("/batches/{batch_id}/adopt")
async def adopt_batch(
    request: Request,
    batch_id: int,
    quantity: int = Form(...),
    pickup_date: str = Form(""),
    delivery_method: str = Form(""),
    delivery_address: str = Form(""),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    batch = db.execute("""
        SELECT id, price, total_quantity, adopted_quantity, status, harvest_date
        FROM batches WHERE id = ?
    """, [batch_id]).fetchone()
    
    if not batch or batch[4] != "open":
        raise HTTPException(status_code=400, detail="该批次不可认养")
    
    remaining = batch[2] - batch[3]
    if quantity <= 0 or quantity > remaining:
        raise HTTPException(status_code=400, detail=f"可认养数量不足，剩余{remaining}{batch[4]}")
    
    total_price = batch[1] * quantity
    
    db.execute("""
        INSERT INTO adoptions (batch_id, consumer_id, quantity, total_price, pickup_date,
                               delivery_method, delivery_address, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
    """, [batch_id, consumer_id, quantity, total_price,
          pickup_date if pickup_date else None,
          delivery_method, delivery_address])
    
    db.execute("""
        UPDATE batches SET adopted_quantity = adopted_quantity + ?
        WHERE id = ?
    """, [quantity, batch_id])
    
    return RedirectResponse(f"/consumer/my-adoptions", status_code=303)


@router.get("/my-adoptions", response_class=HTMLResponse)
async def my_adoptions(
    request: Request,
    status_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    query = """
        SELECT a.id, a.quantity, a.total_price, a.pickup_date, a.delivery_method,
               a.delivery_address, a.status, a.created_at,
               b.name as batch_name, b.unit, b.price as unit_price,
               p.name as plot_name, p.type as plot_type,
               u.full_name as farmer_name
        FROM adoptions a
        JOIN batches b ON a.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        WHERE a.consumer_id = ?
    """
    params = [consumer_id]
    
    if status_filter:
        query += " AND a.status = ?"
        params.append(status_filter)
    
    query += " ORDER BY a.created_at DESC"
    
    adoptions = db.execute(query, params).fetchall()
    
    adoption_list = []
    for a in adoptions:
        adoption_list.append({
            "id": a[0],
            "quantity": a[1],
            "total_price": a[2],
            "pickup_date": str(a[3]) if a[3] else "",
            "delivery_method": a[4],
            "delivery_address": a[5],
            "status": a[6],
            "created_at": str(a[7]),
            "batch_name": a[8],
            "unit": a[9],
            "unit_price": a[10],
            "plot_name": a[11],
            "plot_type": a[12],
            "farmer_name": a[13]
        })
    
    return TemplateResponse("consumer/my_adoptions.html", {
        "request": request,
        "current_user": current_user,
        "adoptions": adoption_list,
        "status_filter": status_filter
    })


@router.get("/adoptions/{adoption_id}", response_class=HTMLResponse)
async def adoption_detail(
    request: Request,
    adoption_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    adoption = db.execute("""
        SELECT a.id, a.quantity, a.total_price, a.pickup_date, a.delivery_method,
               a.delivery_address, a.status, a.created_at,
               b.id as batch_id, b.name as batch_name, b.unit, b.price as unit_price,
               b.harvest_date, b.description as batch_description,
               p.id as plot_id, p.name as plot_name, p.type as plot_type, p.location,
               u.full_name as farmer_name, u.id as farmer_id
        FROM adoptions a
        JOIN batches b ON a.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        WHERE a.id = ? AND a.consumer_id = ?
    """, [adoption_id, consumer_id]).fetchone()
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    adoption_dict = {
        "id": adoption[0],
        "quantity": adoption[1],
        "total_price": adoption[2],
        "pickup_date": str(adoption[3]) if adoption[3] else "",
        "delivery_method": adoption[4],
        "delivery_address": adoption[5],
        "status": adoption[6],
        "created_at": str(adoption[7]),
        "batch_id": adoption[8],
        "batch_name": adoption[9],
        "unit": adoption[10],
        "unit_price": adoption[11],
        "harvest_date": str(adoption[12]) if adoption[12] else "",
        "batch_description": adoption[13],
        "plot_id": adoption[14],
        "plot_name": adoption[15],
        "plot_type": adoption[16],
        "plot_location": adoption[17],
        "farmer_name": adoption[18],
        "farmer_id": adoption[19]
    }
    
    after_sales = db.execute("""
        SELECT id, type, description, status, resolution, created_at, resolved_at
        FROM after_sales
        WHERE adoption_id = ?
        ORDER BY created_at DESC
    """, [adoption_id]).fetchall()
    
    after_sale_list = []
    for s in after_sales:
        after_sale_list.append({
            "id": s[0],
            "type": s[1],
            "description": s[2],
            "status": s[3],
            "resolution": s[4],
            "created_at": str(s[5]),
            "resolved_at": str(s[6]) if s[6] else ""
        })
    
    weather_events = db.execute("""
        SELECT w.id, w.event_type, w.description, w.severity, w.affected_date, w.created_at
        FROM weather_events w
        JOIN adoptions a ON w.batch_id = a.batch_id
        WHERE a.id = ?
        ORDER BY w.created_at DESC
    """, [adoption_id]).fetchall()
    
    event_list = []
    for w in weather_events:
        event_list.append({
            "id": w[0],
            "event_type": w[1],
            "description": w[2],
            "severity": w[3],
            "affected_date": str(w[4]) if w[4] else "",
            "created_at": str(w[5])
        })
    
    return TemplateResponse("consumer/adoption_detail.html", {
        "request": request,
        "current_user": current_user,
        "adoption": adoption_dict,
        "after_sales": after_sale_list,
        "weather_events": event_list
    })


@router.post("/adoptions/{adoption_id}/reschedule")
async def reschedule_adoption(
    request: Request,
    adoption_id: int,
    new_pickup_date: str = Form(...),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    adoption = db.execute("""
        SELECT id, status FROM adoptions WHERE id = ? AND consumer_id = ?
    """, [adoption_id, consumer_id]).fetchone()
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    if adoption[1] not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="该订单状态不支持改期")
    
    db.execute("""
        UPDATE adoptions SET pickup_date = ? WHERE id = ?
    """, [new_pickup_date, adoption_id])
    
    return RedirectResponse(f"/consumer/adoptions/{adoption_id}", status_code=303)


@router.post("/adoptions/{adoption_id}/refund")
async def refund_adoption(
    request: Request,
    adoption_id: int,
    reason: str = Form(""),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    adoption = db.execute("""
        SELECT id, status, quantity, batch_id FROM adoptions WHERE id = ? AND consumer_id = ?
    """, [adoption_id, consumer_id]).fetchone()
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    if adoption[1] not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="该订单状态不支持退款")
    
    db.execute("UPDATE adoptions SET status = 'refunded' WHERE id = ?", [adoption_id])
    
    db.execute("""
        UPDATE batches SET adopted_quantity = adopted_quantity - ?
        WHERE id = ?
    """, [adoption[2], adoption[3]])
    
    db.execute("""
        INSERT INTO after_sales (adoption_id, type, description, status, resolution)
        VALUES (?, 'refund', ?, 'resolved', '已退款')
    """, [adoption_id, reason or "消费者申请退款"])
    
    return RedirectResponse(f"/consumer/adoptions/{adoption_id}", status_code=303)


@router.post("/adoptions/{adoption_id}/switch-batch")
async def switch_batch(
    request: Request,
    adoption_id: int,
    new_batch_id: int = Form(...),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    adoption = db.execute("""
        SELECT a.id, a.status, a.quantity, a.total_price, a.batch_id
        FROM adoptions a WHERE a.id = ? AND a.consumer_id = ?
    """, [adoption_id, consumer_id]).fetchone()
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    if adoption[1] not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="该订单状态不支持换批次")
    
    old_batch_id = adoption[3]
    quantity = adoption[2]
    
    new_batch = db.execute("""
        SELECT id, price, total_quantity, adopted_quantity, status, plot_id
        FROM batches WHERE id = ?
    """, [new_batch_id]).fetchone()
    
    if not new_batch or new_batch[4] != "open":
        raise HTTPException(status_code=400, detail="新批次不可认养")
    
    old_batch_plot = db.execute("SELECT plot_id FROM batches WHERE id = ?", [old_batch_id]).fetchone()
    if old_batch_plot[0] != new_batch[5]:
        raise HTTPException(status_code=400, detail="只能更换同一地块的批次")
    
    remaining = new_batch[2] - new_batch[3]
    if quantity > remaining:
        raise HTTPException(status_code=400, detail="新批次数量不足")
    
    new_total_price = new_batch[1] * quantity
    
    db.execute("""
        UPDATE batches SET adopted_quantity = adopted_quantity - ? WHERE id = ?
    """, [quantity, old_batch_id])
    
    db.execute("""
        UPDATE batches SET adopted_quantity = adopted_quantity + ? WHERE id = ?
    """, [quantity, new_batch_id])
    
    db.execute("""
        UPDATE adoptions SET batch_id = ?, total_price = ?, status = 'pending'
        WHERE id = ?
    """, [new_batch_id, new_total_price, adoption_id])
    
    return RedirectResponse(f"/consumer/adoptions/{adoption_id}", status_code=303)


@router.post("/adoptions/{adoption_id}/after-sale")
async def create_after_sale(
    request: Request,
    adoption_id: int,
    type: str = Form(...),
    description: str = Form(...),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "consumer":
        return RedirectResponse("/auth/login", status_code=303)
    
    consumer_id = current_user["id"]
    
    adoption = db.execute("""
        SELECT id FROM adoptions WHERE id = ? AND consumer_id = ?
    """, [adoption_id, consumer_id]).fetchone()
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    db.execute("""
        INSERT INTO after_sales (adoption_id, type, description, status)
        VALUES (?, ?, ?, 'pending')
    """, [adoption_id, type, description])
    
    return RedirectResponse(f"/consumer/adoptions/{adoption_id}", status_code=303)
