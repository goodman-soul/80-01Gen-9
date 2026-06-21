from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional
import duckdb

from app.database import get_db
from app.utils.auth import get_current_user, require_role
from app.utils.templates import TemplateResponse

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def farmer_dashboard(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    stats = db.execute("""
        SELECT 
            COUNT(DISTINCT p.id) as plot_count,
            COUNT(DISTINCT b.id) as batch_count,
            COALESCE(SUM(a.quantity), 0) as total_adopted,
            COALESCE(SUM(a.total_price), 0) as total_revenue
        FROM plots p
        LEFT JOIN batches b ON p.id = b.plot_id
        LEFT JOIN adoptions a ON b.id = a.batch_id
        WHERE p.farmer_id = ?
    """, [farmer_id]).fetchone()
    
    plots = db.execute("""
        SELECT p.id, p.name, p.type, p.area, p.location, p.status,
               COUNT(b.id) as batch_count
        FROM plots p
        LEFT JOIN batches b ON p.id = b.plot_id
        WHERE p.farmer_id = ?
        GROUP BY p.id, p.name, p.type, p.area, p.location, p.status, p.created_at
        ORDER BY p.created_at DESC
    """, [farmer_id]).fetchall()
    
    plot_list = []
    for p in plots:
        plot_list.append({
            "id": p[0],
            "name": p[1],
            "type": p[2],
            "area": p[3],
            "location": p[4],
            "status": p[5],
            "batch_count": p[6]
        })
    
    pending_orders = db.execute("""
        SELECT a.id, a.quantity, a.total_price, a.status, a.created_at,
               b.name as batch_name,
               u.full_name as consumer_name, u.phone as consumer_phone
        FROM adoptions a
        JOIN batches b ON a.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON a.consumer_id = u.id
        WHERE p.farmer_id = ? AND a.status = 'pending'
        ORDER BY a.created_at DESC
        LIMIT 10
    """, [farmer_id]).fetchall()
    
    order_list = []
    for o in pending_orders:
        order_list.append({
            "id": o[0],
            "quantity": o[1],
            "total_price": o[2],
            "status": o[3],
            "created_at": str(o[4]),
            "batch_name": o[5],
            "consumer_name": o[6],
            "consumer_phone": o[7]
        })
    
    weather_events = db.execute("""
        SELECT w.id, w.event_type, w.description, w.severity, w.affected_date, w.created_at,
               b.name as batch_name
        FROM weather_events w
        JOIN batches b ON w.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        WHERE p.farmer_id = ?
        ORDER BY w.created_at DESC
        LIMIT 5
    """, [farmer_id]).fetchall()
    
    event_list = []
    for w in weather_events:
        event_list.append({
            "id": w[0],
            "event_type": w[1],
            "description": w[2],
            "severity": w[3],
            "affected_date": str(w[4]),
            "created_at": str(w[5]),
            "batch_name": w[6]
        })
    
    return TemplateResponse("farmer/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": {
            "plot_count": stats[0],
            "batch_count": stats[1],
            "total_adopted": stats[2],
            "total_revenue": stats[3]
        },
        "plots": plot_list,
        "pending_orders": order_list,
        "weather_events": event_list
    })


@router.get("/plots", response_class=HTMLResponse)
async def plot_list(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    plots = db.execute("""
        SELECT p.id, p.name, p.type, p.area, p.location, p.description, p.status, p.created_at,
               COUNT(b.id) as batch_count
        FROM plots p
        LEFT JOIN batches b ON p.id = b.plot_id
        WHERE p.farmer_id = ?
        GROUP BY p.id, p.name, p.type, p.area, p.location, p.description, p.status, p.created_at
        ORDER BY p.created_at DESC
    """, [farmer_id]).fetchall()
    
    plot_list = []
    for p in plots:
        plot_list.append({
            "id": p[0],
            "name": p[1],
            "type": p[2],
            "area": p[3],
            "location": p[4],
            "description": p[5],
            "status": p[6],
            "created_at": str(p[7]),
            "batch_count": p[8]
        })
    
    return TemplateResponse("farmer/plots.html", {
        "request": request,
        "current_user": current_user,
        "plots": plot_list
    })


@router.get("/plots/new", response_class=HTMLResponse)
async def new_plot_page(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    return TemplateResponse("farmer/plot_form.html", {
        "request": request,
        "current_user": current_user,
        "plot": None,
        "error": None
    })


@router.post("/plots/new")
async def create_plot(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    area: float = Form(...),
    location: str = Form(""),
    description: str = Form(""),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    db.execute("""
        INSERT INTO plots (farmer_id, name, type, area, location, description, status)
        VALUES (?, ?, ?, ?, ?, ?, 'active')
    """, [farmer_id, name, type, area, location, description])
    
    return RedirectResponse("/farmer/plots", status_code=303)


@router.get("/plots/{plot_id}/edit", response_class=HTMLResponse)
async def edit_plot_page(
    request: Request,
    plot_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    plot = db.execute("""
        SELECT id, name, type, area, location, description, status
        FROM plots WHERE id = ? AND farmer_id = ?
    """, [plot_id, farmer_id]).fetchone()
    
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在")
    
    plot_dict = {
        "id": plot[0],
        "name": plot[1],
        "type": plot[2],
        "area": plot[3],
        "location": plot[4],
        "description": plot[5],
        "status": plot[6]
    }
    
    return TemplateResponse("farmer/plot_form.html", {
        "request": request,
        "current_user": current_user,
        "plot": plot_dict,
        "error": None
    })


@router.post("/plots/{plot_id}/edit")
async def update_plot(
    request: Request,
    plot_id: int,
    name: str = Form(...),
    type: str = Form(...),
    area: float = Form(...),
    location: str = Form(""),
    description: str = Form(""),
    status: str = Form("active"),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    db.execute("""
        UPDATE plots SET name = ?, type = ?, area = ?, location = ?, description = ?, status = ?
        WHERE id = ? AND farmer_id = ?
    """, [name, type, area, location, description, status, plot_id, farmer_id])
    
    return RedirectResponse("/farmer/plots", status_code=303)


@router.get("/batches", response_class=HTMLResponse)
async def batch_list(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    batches = db.execute("""
        SELECT b.id, b.name, b.description, b.price, b.unit, b.total_quantity,
               b.adopted_quantity, b.harvest_date, b.delivery_methods, b.status, b.created_at,
               p.name as plot_name, p.type as plot_type
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        WHERE p.farmer_id = ?
        ORDER BY b.created_at DESC
    """, [farmer_id]).fetchall()
    
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
            "delivery_methods": b[8],
            "status": b[9],
            "created_at": str(b[10]),
            "plot_name": b[11],
            "plot_type": b[12],
            "progress": progress
        })
    
    return TemplateResponse("farmer/batches.html", {
        "request": request,
        "current_user": current_user,
        "batches": batch_list
    })


@router.get("/batches/new", response_class=HTMLResponse)
async def new_batch_page(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    plots = db.execute("""
        SELECT id, name, type FROM plots WHERE farmer_id = ? AND status = 'active'
    """, [farmer_id]).fetchall()
    
    plot_list = [{"id": p[0], "name": p[1], "type": p[2]} for p in plots]
    
    return TemplateResponse("farmer/batch_form.html", {
        "request": request,
        "current_user": current_user,
        "batch": None,
        "plots": plot_list,
        "error": None
    })


@router.post("/batches/new")
async def create_batch(
    request: Request,
    plot_id: int = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    unit: str = Form(...),
    total_quantity: int = Form(...),
    harvest_date: str = Form(""),
    delivery_methods: str = Form(""),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    plot = db.execute("SELECT id FROM plots WHERE id = ? AND farmer_id = ?", [plot_id, farmer_id]).fetchone()
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在")
    
    db.execute("""
        INSERT INTO batches (plot_id, name, description, price, unit, total_quantity,
                             adopted_quantity, harvest_date, delivery_methods, status)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'open')
    """, [plot_id, name, description, price, unit, total_quantity,
          harvest_date if harvest_date else None, delivery_methods])
    
    return RedirectResponse("/farmer/batches", status_code=303)


@router.get("/batches/{batch_id}/edit", response_class=HTMLResponse)
async def edit_batch_page(
    request: Request,
    batch_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    batch = db.execute("""
        SELECT b.id, b.plot_id, b.name, b.description, b.price, b.unit, b.total_quantity,
               b.adopted_quantity, b.harvest_date, b.delivery_methods, b.status
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        WHERE b.id = ? AND p.farmer_id = ?
    """, [batch_id, farmer_id]).fetchone()
    
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    batch_dict = {
        "id": batch[0],
        "plot_id": batch[1],
        "name": batch[2],
        "description": batch[3],
        "price": batch[4],
        "unit": batch[5],
        "total_quantity": batch[6],
        "adopted_quantity": batch[7],
        "harvest_date": str(batch[8]) if batch[8] else "",
        "delivery_methods": batch[9],
        "status": batch[10]
    }
    
    plots = db.execute("""
        SELECT id, name, type FROM plots WHERE farmer_id = ? AND status = 'active'
    """, [farmer_id]).fetchall()
    
    plot_list = [{"id": p[0], "name": p[1], "type": p[2]} for p in plots]
    
    return TemplateResponse("farmer/batch_form.html", {
        "request": request,
        "current_user": current_user,
        "batch": batch_dict,
        "plots": plot_list,
        "error": None
    })


@router.post("/batches/{batch_id}/edit")
async def update_batch(
    request: Request,
    batch_id: int,
    name: str = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    unit: str = Form(...),
    total_quantity: int = Form(...),
    harvest_date: str = Form(""),
    delivery_methods: str = Form(""),
    status: str = Form("open"),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    db.execute("""
        UPDATE batches SET name = ?, description = ?, price = ?, unit = ?, total_quantity = ?,
                           harvest_date = ?, delivery_methods = ?, status = ?
        WHERE id = ? AND plot_id IN (SELECT id FROM plots WHERE farmer_id = ?)
    """, [name, description, price, unit, total_quantity,
          harvest_date if harvest_date else None, delivery_methods, status,
          batch_id, farmer_id])
    
    return RedirectResponse("/farmer/batches", status_code=303)


@router.get("/adoptions", response_class=HTMLResponse)
async def adoption_list(
    request: Request,
    status_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    query = """
        SELECT a.id, a.quantity, a.total_price, a.pickup_date, a.delivery_method,
               a.delivery_address, a.status, a.created_at,
               b.name as batch_name, b.unit,
               p.name as plot_name,
               u.full_name as consumer_name, u.phone as consumer_phone, u.email as consumer_email
        FROM adoptions a
        JOIN batches b ON a.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON a.consumer_id = u.id
        WHERE p.farmer_id = ?
    """
    params = [farmer_id]
    
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
            "plot_name": a[10],
            "consumer_name": a[11],
            "consumer_phone": a[12],
            "consumer_email": a[13]
        })
    
    return TemplateResponse("farmer/adoptions.html", {
        "request": request,
        "current_user": current_user,
        "adoptions": adoption_list,
        "status_filter": status_filter
    })


@router.post("/adoptions/{adoption_id}/confirm")
async def confirm_adoption(
    request: Request,
    adoption_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    adoption = db.execute("""
        SELECT a.id, a.quantity, b.id as batch_id
        FROM adoptions a
        JOIN batches b ON a.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        WHERE a.id = ? AND p.farmer_id = ?
    """, [adoption_id, farmer_id]).fetchone()
    
    if not adoption:
        raise HTTPException(status_code=404, detail="订单不存在")
    
    db.execute("UPDATE adoptions SET status = 'confirmed' WHERE id = ?", [adoption_id])
    
    return RedirectResponse("/farmer/adoptions", status_code=303)


@router.post("/adoptions/{adoption_id}/complete")
async def complete_adoption(
    request: Request,
    adoption_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    db.execute("""
        UPDATE adoptions SET status = 'completed'
        WHERE id = ? AND batch_id IN (SELECT b.id FROM batches b JOIN plots p ON b.plot_id = p.id WHERE p.farmer_id = ?)
    """, [adoption_id, farmer_id])
    
    return RedirectResponse("/farmer/adoptions", status_code=303)


@router.get("/weather", response_class=HTMLResponse)
async def weather_events(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    events = db.execute("""
        SELECT w.id, w.event_type, w.description, w.severity, w.affected_date, w.created_at,
               b.name as batch_name, b.id as batch_id
        FROM weather_events w
        JOIN batches b ON w.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        WHERE p.farmer_id = ?
        ORDER BY w.created_at DESC
    """, [farmer_id]).fetchall()
    
    event_list = []
    for w in events:
        event_list.append({
            "id": w[0],
            "event_type": w[1],
            "description": w[2],
            "severity": w[3],
            "affected_date": str(w[4]),
            "created_at": str(w[5]),
            "batch_name": w[6],
            "batch_id": w[7]
        })
    
    batches = db.execute("""
        SELECT b.id, b.name
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        WHERE p.farmer_id = ? AND b.status = 'open'
    """, [farmer_id]).fetchall()
    
    batch_list = [{"id": b[0], "name": b[1]} for b in batches]
    
    return TemplateResponse("farmer/weather.html", {
        "request": request,
        "current_user": current_user,
        "events": event_list,
        "batches": batch_list
    })


@router.post("/weather/new")
async def create_weather_event(
    request: Request,
    batch_id: int = Form(...),
    event_type: str = Form(...),
    description: str = Form(""),
    severity: str = Form("moderate"),
    affected_date: str = Form(""),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] not in ["farmer", "admin"]:
        return RedirectResponse("/auth/login", status_code=303)
    
    farmer_id = current_user["id"]
    
    batch = db.execute("""
        SELECT b.id FROM batches b
        JOIN plots p ON b.plot_id = p.id
        WHERE b.id = ? AND p.farmer_id = ?
    """, [batch_id, farmer_id]).fetchone()
    
    if not batch:
        raise HTTPException(status_code=404, detail="批次不存在")
    
    db.execute("""
        INSERT INTO weather_events (batch_id, event_type, description, severity, affected_date)
        VALUES (?, ?, ?, ?, ?)
    """, [batch_id, event_type, description, severity, affected_date if affected_date else None])
    
    return RedirectResponse("/farmer/weather", status_code=303)
