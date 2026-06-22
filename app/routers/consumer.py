from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional
import duckdb

from app.database import get_db
from app.utils.auth import get_current_user
from app.utils.templates import TemplateResponse

router = APIRouter()


def row_to_dict(row, cursor):
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


def fetch_all_dicts(cursor):
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_one_dict(cursor):
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


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
    
    cursor = db.execute(query, params)
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
            "delivery_methods": b["delivery_methods"].split(",") if b["delivery_methods"] else [],
            "status": b["status"],
            "plot_name": b["plot_name"],
            "plot_type": b["plot_type"],
            "plot_location": b["plot_location"],
            "farmer_name": b["farmer_name"],
            "progress": progress,
            "remaining": b["total_quantity"] - b["adopted_quantity"]
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
    
    cursor = db.execute("""
        SELECT b.id, b.name, b.description, b.price, b.unit, b.total_quantity,
               b.adopted_quantity, b.harvest_date, b.delivery_methods, b.status, b.created_at,
               p.name as plot_name, p.type as plot_type, p.location as plot_location,
               p.description as plot_description, p.area,
               u.full_name as farmer_name, u.id as farmer_id
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        WHERE b.id = ?
    """, [batch_id])
    batch = fetch_one_dict(cursor)
    
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    progress = int((batch["adopted_quantity"] / batch["total_quantity"]) * 100) if batch["total_quantity"] > 0 else 0
    
    batch_dict = {
        "id": batch["id"],
        "name": batch["name"],
        "description": batch["description"],
        "price": batch["price"],
        "unit": batch["unit"],
        "total_quantity": batch["total_quantity"],
        "adopted_quantity": batch["adopted_quantity"],
        "harvest_date": str(batch["harvest_date"]) if batch["harvest_date"] else "",
        "delivery_methods": batch["delivery_methods"].split(",") if batch["delivery_methods"] else [],
        "status": batch["status"],
        "created_at": str(batch["created_at"]),
        "plot_name": batch["plot_name"],
        "plot_type": batch["plot_type"],
        "plot_location": batch["plot_location"],
        "plot_description": batch["plot_description"],
        "plot_area": batch["area"],
        "farmer_name": batch["farmer_name"],
        "farmer_id": batch["farmer_id"],
        "progress": progress,
        "remaining": batch["total_quantity"] - batch["adopted_quantity"]
    }
    
    cursor = db.execute("""
        SELECT id, event_type, description, severity, affected_date, created_at
        FROM weather_events
        WHERE batch_id = ?
        ORDER BY created_at DESC
    """, [batch_id])
    weather_events = fetch_all_dicts(cursor)
    
    event_list = []
    for w in weather_events:
        event_list.append({
            "id": w["id"],
            "event_type": w["event_type"],
            "description": w["description"],
            "severity": w["severity"],
            "affected_date": str(w["affected_date"]) if w["affected_date"] else "",
            "created_at": str(w["created_at"])
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
    
    cursor = db.execute("""
        SELECT id, price, total_quantity, adopted_quantity, status, harvest_date, unit
        FROM batches WHERE id = ?
    """, [batch_id])
    batch = fetch_one_dict(cursor)
    
    if not batch or batch["status"] != "open":
        raise HTTPException(status_code=400, detail="该批次不可认养")
    
    remaining = batch["total_quantity"] - batch["adopted_quantity"]
    if quantity <= 0 or quantity > remaining:
        raise HTTPException(status_code=400, detail=f"可认养数量不足，剩余{remaining}{batch['unit']}")
    
    total_price = batch["price"] * quantity
    
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
    
    cursor = db.execute(query, params)
    adoptions = fetch_all_dicts(cursor)
    
    adoption_list = []
    for a in adoptions:
        adoption_list.append({
            "id": a["id"],
            "quantity": a["quantity"],
            "total_price": a["total_price"],
            "pickup_date": str(a["pickup_date"]) if a["pickup_date"] else "",
            "delivery_method": a["delivery_method"],
            "delivery_address": a["delivery_address"],
            "status": a["status"],
            "created_at": str(a["created_at"]),
            "batch_name": a["batch_name"],
            "unit": a["unit"],
            "unit_price": a["unit_price"],
            "plot_name": a["plot_name"],
            "plot_type": a["plot_type"],
            "farmer_name": a["farmer_name"]
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
    
    cursor = db.execute("""
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
    """, [adoption_id, consumer_id])
    adoption = fetch_one_dict(cursor)
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    adoption_dict = {
        "id": adoption["id"],
        "quantity": adoption["quantity"],
        "total_price": adoption["total_price"],
        "pickup_date": str(adoption["pickup_date"]) if adoption["pickup_date"] else "",
        "delivery_method": adoption["delivery_method"],
        "delivery_address": adoption["delivery_address"],
        "status": adoption["status"],
        "created_at": str(adoption["created_at"]),
        "batch_id": adoption["batch_id"],
        "batch_name": adoption["batch_name"],
        "unit": adoption["unit"],
        "unit_price": adoption["unit_price"],
        "harvest_date": str(adoption["harvest_date"]) if adoption["harvest_date"] else "",
        "batch_description": adoption["batch_description"],
        "plot_id": adoption["plot_id"],
        "plot_name": adoption["plot_name"],
        "plot_type": adoption["plot_type"],
        "plot_location": adoption["location"],
        "farmer_name": adoption["farmer_name"],
        "farmer_id": adoption["farmer_id"]
    }
    
    cursor = db.execute("""
        SELECT id, type, description, status, resolution, created_at, resolved_at
        FROM after_sales
        WHERE adoption_id = ?
        ORDER BY created_at DESC
    """, [adoption_id])
    after_sales = fetch_all_dicts(cursor)
    
    after_sale_list = []
    for s in after_sales:
        after_sale_list.append({
            "id": s["id"],
            "type": s["type"],
            "description": s["description"],
            "status": s["status"],
            "resolution": s["resolution"],
            "created_at": str(s["created_at"]),
            "resolved_at": str(s["resolved_at"]) if s["resolved_at"] else ""
        })
    
    cursor = db.execute("""
        SELECT w.id, w.event_type, w.description, w.severity, w.affected_date, w.created_at
        FROM weather_events w
        JOIN adoptions a ON w.batch_id = a.batch_id
        WHERE a.id = ?
        ORDER BY w.created_at DESC
    """, [adoption_id])
    weather_events = fetch_all_dicts(cursor)
    
    event_list = []
    for w in weather_events:
        event_list.append({
            "id": w["id"],
            "event_type": w["event_type"],
            "description": w["description"],
            "severity": w["severity"],
            "affected_date": str(w["affected_date"]) if w["affected_date"] else "",
            "created_at": str(w["created_at"])
        })
    
    cursor = db.execute("""
        SELECT b.id, b.name, b.price, b.unit, b.total_quantity, b.adopted_quantity
        FROM batches b
        WHERE b.plot_id = ? AND b.id != ? AND b.status = 'open'
        ORDER BY b.created_at DESC
    """, [adoption_dict["plot_id"], adoption_dict["batch_id"]])
    available_batches = fetch_all_dicts(cursor)
    
    batch_list = []
    for b in available_batches:
        remaining = b["total_quantity"] - b["adopted_quantity"]
        batch_list.append({
            "id": b["id"],
            "name": b["name"],
            "price": b["price"],
            "unit": b["unit"],
            "remaining": remaining
        })
    
    return TemplateResponse("consumer/adoption_detail.html", {
        "request": request,
        "current_user": current_user,
        "adoption": adoption_dict,
        "after_sales": after_sale_list,
        "weather_events": event_list,
        "available_batches": batch_list
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
    
    cursor = db.execute("""
        SELECT id, status FROM adoptions WHERE id = ? AND consumer_id = ?
    """, [adoption_id, consumer_id])
    adoption = fetch_one_dict(cursor)
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    if adoption["status"] not in ["pending", "confirmed"]:
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
    
    cursor = db.execute("""
        SELECT id, status, quantity, batch_id FROM adoptions WHERE id = ? AND consumer_id = ?
    """, [adoption_id, consumer_id])
    adoption = fetch_one_dict(cursor)
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    if adoption["status"] not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="该订单状态不支持退款")
    
    db.execute("UPDATE adoptions SET status = 'refunded' WHERE id = ?", [adoption_id])
    
    db.execute("""
        UPDATE batches SET adopted_quantity = adopted_quantity - ?
        WHERE id = ?
    """, [adoption["quantity"], adoption["batch_id"]])
    
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
    
    cursor = db.execute("""
        SELECT a.id, a.status, a.quantity, a.total_price, a.batch_id
        FROM adoptions a WHERE a.id = ? AND a.consumer_id = ?
    """, [adoption_id, consumer_id])
    adoption = fetch_one_dict(cursor)
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    if adoption["status"] not in ["pending", "confirmed"]:
        raise HTTPException(status_code=400, detail="该订单状态不支持换批次")
    
    old_batch_id = adoption["batch_id"]
    quantity = adoption["quantity"]
    
    cursor = db.execute("""
        SELECT id, price, total_quantity, adopted_quantity, status, plot_id
        FROM batches WHERE id = ?
    """, [new_batch_id])
    new_batch = fetch_one_dict(cursor)
    
    if not new_batch or new_batch["status"] != "open":
        raise HTTPException(status_code=400, detail="新批次不可认养")
    
    old_batch_plot = db.execute("SELECT plot_id FROM batches WHERE id = ?", [old_batch_id]).fetchone()
    if old_batch_plot[0] != new_batch["plot_id"]:
        raise HTTPException(status_code=400, detail="只能更换同一地块的批次")
    
    remaining = new_batch["total_quantity"] - new_batch["adopted_quantity"]
    if quantity > remaining:
        raise HTTPException(status_code=400, detail="新批次数量不足")
    
    new_total_price = new_batch["price"] * quantity
    
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
    
    cursor = db.execute("""
        SELECT id FROM adoptions WHERE id = ? AND consumer_id = ?
    """, [adoption_id, consumer_id])
    adoption = fetch_one_dict(cursor)
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    db.execute("""
        INSERT INTO after_sales (adoption_id, type, description, status)
        VALUES (?, ?, ?, 'pending')
    """, [adoption_id, type, description])
    
    return RedirectResponse(f"/consumer/adoptions/{adoption_id}", status_code=303)
