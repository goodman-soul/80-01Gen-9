from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from typing import Optional
import duckdb

from app.database import get_db
from app.utils.auth import get_current_user
from app.utils.templates import TemplateResponse

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    stats = db.execute("""
        SELECT 
            (SELECT COUNT(*) FROM users WHERE role = 'consumer') as consumer_count,
            (SELECT COUNT(*) FROM users WHERE role = 'farmer') as farmer_count,
            (SELECT COUNT(*) FROM plots WHERE status = 'active') as plot_count,
            (SELECT COUNT(*) FROM batches WHERE status = 'open') as open_batch_count,
            (SELECT COUNT(*) FROM adoptions) as total_adoptions,
            (SELECT COALESCE(SUM(total_price), 0) FROM adoptions WHERE status IN ('confirmed', 'completed')) as total_revenue,
            (SELECT COUNT(*) FROM after_sales WHERE status = 'pending') as pending_after_sales
    """).fetchone()
    
    stats_dict = {
        "consumer_count": stats[0],
        "farmer_count": stats[1],
        "plot_count": stats[2],
        "open_batch_count": stats[3],
        "total_adoptions": stats[4],
        "total_revenue": stats[5],
        "pending_after_sales": stats[6]
    }
    
    plots_summary = db.execute("""
        SELECT 
            p.id, p.name, p.type, p.location,
            u.full_name as farmer_name,
            COUNT(b.id) as batch_count,
            COALESCE(SUM(b.adopted_quantity), 0) as total_adopted,
            COUNT(DISTINCT a.consumer_id) as adopter_count
        FROM plots p
        JOIN users u ON p.farmer_id = u.id
        LEFT JOIN batches b ON p.id = b.plot_id
        LEFT JOIN adoptions a ON b.id = a.batch_id
        WHERE p.status = 'active'
        GROUP BY p.id, p.name, p.type, p.location, u.full_name
        ORDER BY adopter_count DESC
        LIMIT 10
    """).fetchall()
    
    plot_list = []
    for p in plots_summary:
        plot_list.append({
            "id": p[0],
            "name": p[1],
            "type": p[2],
            "location": p[3],
            "farmer_name": p[4],
            "batch_count": p[5],
            "total_adopted": p[6],
            "adopter_count": p[7]
        })
    
    batches_progress = db.execute("""
        SELECT 
            b.id, b.name, b.total_quantity, b.adopted_quantity, b.harvest_date, b.status,
            p.name as plot_name, p.type as plot_type,
            u.full_name as farmer_name
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        ORDER BY b.created_at DESC
        LIMIT 10
    """).fetchall()
    
    batch_list = []
    for b in batches_progress:
        progress = int((b[3] / b[2]) * 100) if b[2] > 0 else 0
        batch_list.append({
            "id": b[0],
            "name": b[1],
            "total_quantity": b[2],
            "adopted_quantity": b[3],
            "harvest_date": str(b[4]) if b[4] else "",
            "status": b[5],
            "plot_name": b[6],
            "plot_type": b[7],
            "farmer_name": b[8],
            "progress": progress
        })
    
    pending_after_sales = db.execute("""
        SELECT 
            a.id, a.type, a.description, a.status, a.created_at,
            ad.id as adoption_id, ad.quantity, ad.total_price,
            b.name as batch_name,
            u.full_name as consumer_name
        FROM after_sales a
        JOIN adoptions ad ON a.adoption_id = ad.id
        JOIN batches b ON ad.batch_id = b.id
        JOIN users u ON ad.consumer_id = u.id
        WHERE a.status = 'pending'
        ORDER BY a.created_at DESC
        LIMIT 10
    """).fetchall()
    
    after_sale_list = []
    for s in pending_after_sales:
        after_sale_list.append({
            "id": s[0],
            "type": s[1],
            "description": s[2],
            "status": s[3],
            "created_at": str(s[4]),
            "adoption_id": s[5],
            "quantity": s[6],
            "total_price": s[7],
            "batch_name": s[8],
            "consumer_name": s[9]
        })
    
    return TemplateResponse("admin/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": stats_dict,
        "top_plots": plot_list,
        "recent_batches": batch_list,
        "pending_after_sales": after_sale_list
    })


@router.get("/plots", response_class=HTMLResponse)
async def admin_plots(
    request: Request,
    type_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    query = """
        SELECT 
            p.id, p.name, p.type, p.area, p.location, p.status, p.created_at,
            u.full_name as farmer_name, u.id as farmer_id,
            COUNT(DISTINCT b.id) as batch_count,
            COALESCE(SUM(b.adopted_quantity), 0) as total_adopted,
            COUNT(DISTINCT a.consumer_id) as adopter_count
        FROM plots p
        JOIN users u ON p.farmer_id = u.id
        LEFT JOIN batches b ON p.id = b.plot_id
        LEFT JOIN adoptions a ON b.id = a.batch_id
        WHERE 1=1
    """
    params = []
    
    if type_filter:
        query += " AND p.type = ?"
        params.append(type_filter)
    
    query += " GROUP BY p.id, p.name, p.type, p.area, p.location, p.status, p.created_at, u.full_name, u.id"
    query += " ORDER BY p.created_at DESC"
    
    plots = db.execute(query, params).fetchall()
    
    plot_list = []
    for p in plots:
        plot_list.append({
            "id": p[0],
            "name": p[1],
            "type": p[2],
            "area": p[3],
            "location": p[4],
            "status": p[5],
            "created_at": str(p[6]),
            "farmer_name": p[7],
            "farmer_id": p[8],
            "batch_count": p[9],
            "total_adopted": p[10],
            "adopter_count": p[11]
        })
    
    return TemplateResponse("admin/plots.html", {
        "request": request,
        "current_user": current_user,
        "plots": plot_list,
        "type_filter": type_filter
    })


@router.get("/plots/{plot_id}", response_class=HTMLResponse)
async def admin_plot_detail(
    request: Request,
    plot_id: int,
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    plot = db.execute("""
        SELECT 
            p.id, p.name, p.type, p.area, p.location, p.description, p.status, p.created_at,
            u.full_name as farmer_name, u.email as farmer_email, u.phone as farmer_phone
        FROM plots p
        JOIN users u ON p.farmer_id = u.id
        WHERE p.id = ?
    """, [plot_id]).fetchone()
    
    if not plot:
        raise HTTPException(status_code=404, detail="地块不存在")
    
    plot_dict = {
        "id": plot[0],
        "name": plot[1],
        "type": plot[2],
        "area": plot[3],
        "location": plot[4],
        "description": plot[5],
        "status": plot[6],
        "created_at": str(plot[7]),
        "farmer_name": plot[8],
        "farmer_email": plot[9],
        "farmer_phone": plot[10]
    }
    
    batches = db.execute("""
        SELECT 
            b.id, b.name, b.total_quantity, b.adopted_quantity, b.price, b.unit,
            b.harvest_date, b.status, b.created_at,
            COUNT(a.id) as adoption_count,
            COUNT(DISTINCT a.consumer_id) as adopter_count
        FROM batches b
        LEFT JOIN adoptions a ON b.id = a.batch_id
        WHERE b.plot_id = ?
        GROUP BY b.id, b.name, b.total_quantity, b.adopted_quantity, b.price, b.unit,
                 b.harvest_date, b.status, b.created_at
        ORDER BY b.created_at DESC
    """, [plot_id]).fetchall()
    
    batch_list = []
    for b in batches:
        progress = int((b[3] / b[2]) * 100) if b[2] > 0 else 0
        batch_list.append({
            "id": b[0],
            "name": b[1],
            "total_quantity": b[2],
            "adopted_quantity": b[3],
            "price": b[4],
            "unit": b[5],
            "harvest_date": str(b[6]) if b[6] else "",
            "status": b[7],
            "created_at": str(b[8]),
            "adoption_count": b[9],
            "adopter_count": b[10],
            "progress": progress
        })
    
    return TemplateResponse("admin/plot_detail.html", {
        "request": request,
        "current_user": current_user,
        "plot": plot_dict,
        "batches": batch_list
    })


@router.get("/batches", response_class=HTMLResponse)
async def admin_batches(
    request: Request,
    status_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    query = """
        SELECT 
            b.id, b.name, b.description, b.price, b.unit, b.total_quantity,
            b.adopted_quantity, b.harvest_date, b.status, b.created_at,
            p.name as plot_name, p.type as plot_type,
            u.full_name as farmer_name,
            COUNT(a.id) as adoption_count,
            COUNT(DISTINCT a.consumer_id) as adopter_count
        FROM batches b
        JOIN plots p ON b.plot_id = p.id
        JOIN users u ON p.farmer_id = u.id
        LEFT JOIN adoptions a ON b.id = a.batch_id
        WHERE 1=1
    """
    params = []
    
    if status_filter:
        query += " AND b.status = ?"
        params.append(status_filter)
    
    query += " GROUP BY b.id, b.name, b.description, b.price, b.unit, b.total_quantity,"
    query += " b.adopted_quantity, b.harvest_date, b.status, b.created_at, p.name, p.type, u.full_name"
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
            "status": b[8],
            "created_at": str(b[9]),
            "plot_name": b[10],
            "plot_type": b[11],
            "farmer_name": b[12],
            "adoption_count": b[13],
            "adopter_count": b[14],
            "progress": progress
        })
    
    return TemplateResponse("admin/batches.html", {
        "request": request,
        "current_user": current_user,
        "batches": batch_list,
        "status_filter": status_filter
    })


@router.get("/adoptions", response_class=HTMLResponse)
async def admin_adoptions(
    request: Request,
    status_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    query = """
        SELECT 
            a.id, a.quantity, a.total_price, a.pickup_date, a.delivery_method,
            a.status, a.created_at,
            b.name as batch_name, b.unit,
            p.name as plot_name,
            u1.full_name as consumer_name,
            u2.full_name as farmer_name
        FROM adoptions a
        JOIN batches b ON a.batch_id = b.id
        JOIN plots p ON b.plot_id = p.id
        JOIN users u1 ON a.consumer_id = u1.id
        JOIN users u2 ON p.farmer_id = u2.id
        WHERE 1=1
    """
    params = []
    
    if status_filter:
        query += " AND a.status = ?"
        params.append(status_filter)
    
    query += " ORDER BY a.created_at DESC"
    query += " LIMIT 50"
    
    adoptions = db.execute(query, params).fetchall()
    
    adoption_list = []
    for a in adoptions:
        adoption_list.append({
            "id": a[0],
            "quantity": a[1],
            "total_price": a[2],
            "pickup_date": str(a[3]) if a[3] else "",
            "delivery_method": a[4],
            "status": a[5],
            "created_at": str(a[6]),
            "batch_name": a[7],
            "unit": a[8],
            "plot_name": a[9],
            "consumer_name": a[10],
            "farmer_name": a[11]
        })
    
    return TemplateResponse("admin/adoptions.html", {
        "request": request,
        "current_user": current_user,
        "adoptions": adoption_list,
        "status_filter": status_filter
    })


@router.get("/after-sales", response_class=HTMLResponse)
async def admin_after_sales(
    request: Request,
    status_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    query = """
        SELECT 
            a.id, a.type, a.description, a.status, a.resolution, a.created_at, a.resolved_at,
            ad.id as adoption_id, ad.quantity, ad.total_price, ad.status as adoption_status,
            b.name as batch_name,
            u.full_name as consumer_name
        FROM after_sales a
        JOIN adoptions ad ON a.adoption_id = ad.id
        JOIN batches b ON ad.batch_id = b.id
        JOIN users u ON ad.consumer_id = u.id
        WHERE 1=1
    """
    params = []
    
    if status_filter:
        query += " AND a.status = ?"
        params.append(status_filter)
    
    query += " ORDER BY a.created_at DESC"
    
    after_sales = db.execute(query, params).fetchall()
    
    after_sale_list = []
    for s in after_sales:
        after_sale_list.append({
            "id": s[0],
            "type": s[1],
            "description": s[2],
            "status": s[3],
            "resolution": s[4],
            "created_at": str(s[5]),
            "resolved_at": str(s[6]) if s[6] else "",
            "adoption_id": s[7],
            "quantity": s[8],
            "total_price": s[9],
            "adoption_status": s[10],
            "batch_name": s[11],
            "consumer_name": s[12]
        })
    
    return TemplateResponse("admin/after_sales.html", {
        "request": request,
        "current_user": current_user,
        "after_sales": after_sale_list,
        "status_filter": status_filter
    })


@router.post("/after-sales/{after_sale_id}/resolve")
async def resolve_after_sale(
    request: Request,
    after_sale_id: int,
    resolution: str = Form(""),
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    db.execute("""
        UPDATE after_sales SET status = 'resolved', resolution = ?, resolved_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, [resolution, after_sale_id])
    
    return RedirectResponse("/admin/after-sales", status_code=303)


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    role_filter: str = "",
    db: duckdb.DuckDBPyConnection = Depends(get_db)
):
    current_user = await get_current_user(request, db)
    if not current_user or current_user["role"] != "admin":
        return RedirectResponse("/auth/login", status_code=303)
    
    query = """
        SELECT id, username, email, full_name, phone, role, status, created_at
        FROM users
        WHERE 1=1
    """
    params = []
    
    if role_filter:
        query += " AND role = ?"
        params.append(role_filter)
    
    query += " ORDER BY created_at DESC"
    
    users = db.execute(query, params).fetchall()
    
    user_list = []
    for u in users:
        user_list.append({
            "id": u[0],
            "username": u[1],
            "email": u[2],
            "full_name": u[3],
            "phone": u[4],
            "role": u[5],
            "status": u[6] if len(u) > 6 else "active",
            "created_at": str(u[7]) if len(u) > 7 else ""
        })
    
    return TemplateResponse("admin/users.html", {
        "request": request,
        "current_user": current_user,
        "users": user_list,
        "role_filter": role_filter
    })
