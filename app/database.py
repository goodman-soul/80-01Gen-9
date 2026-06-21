import duckdb
import os
from pathlib import Path

DB_PATH = os.path.join(Path(__file__).parent.parent, "data", "farm.db")


def get_db():
    conn = duckdb.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    conn = duckdb.connect(DB_PATH)
    
    conn.execute("CREATE SEQUENCE IF NOT EXISTS users_id_seq START 1")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY DEFAULT nextval('users_id_seq'),
        username VARCHAR UNIQUE NOT NULL,
        email VARCHAR UNIQUE NOT NULL,
        password_hash VARCHAR NOT NULL,
        full_name VARCHAR,
        phone VARCHAR,
        role VARCHAR NOT NULL DEFAULT 'consumer',
        status VARCHAR NOT NULL DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.execute("CREATE SEQUENCE IF NOT EXISTS plots_id_seq START 1")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS plots (
        id INTEGER PRIMARY KEY DEFAULT nextval('plots_id_seq'),
        farmer_id INTEGER NOT NULL,
        name VARCHAR NOT NULL,
        type VARCHAR NOT NULL,
        area DECIMAL(10,2),
        location VARCHAR,
        description TEXT,
        image_url VARCHAR,
        status VARCHAR DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (farmer_id) REFERENCES users(id)
    )
    """)
    
    conn.execute("CREATE SEQUENCE IF NOT EXISTS batches_id_seq START 1")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY DEFAULT nextval('batches_id_seq'),
        plot_id INTEGER NOT NULL,
        name VARCHAR NOT NULL,
        description TEXT,
        price DECIMAL(10,2) NOT NULL,
        unit VARCHAR NOT NULL,
        total_quantity INTEGER NOT NULL,
        adopted_quantity INTEGER DEFAULT 0,
        harvest_date DATE,
        delivery_methods VARCHAR,
        status VARCHAR DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (plot_id) REFERENCES plots(id)
    )
    """)
    
    conn.execute("CREATE SEQUENCE IF NOT EXISTS adoptions_id_seq START 1")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS adoptions (
        id INTEGER PRIMARY KEY DEFAULT nextval('adoptions_id_seq'),
        batch_id INTEGER NOT NULL,
        consumer_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL,
        total_price DECIMAL(10,2) NOT NULL,
        pickup_date DATE,
        delivery_method VARCHAR,
        delivery_address TEXT,
        status VARCHAR DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES batches(id),
        FOREIGN KEY (consumer_id) REFERENCES users(id)
    )
    """)
    
    conn.execute("CREATE SEQUENCE IF NOT EXISTS weather_events_id_seq START 1")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS weather_events (
        id INTEGER PRIMARY KEY DEFAULT nextval('weather_events_id_seq'),
        batch_id INTEGER NOT NULL,
        event_type VARCHAR NOT NULL,
        description TEXT,
        severity VARCHAR DEFAULT 'moderate',
        affected_date DATE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (batch_id) REFERENCES batches(id)
    )
    """)
    
    conn.execute("CREATE SEQUENCE IF NOT EXISTS after_sales_id_seq START 1")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS after_sales (
        id INTEGER PRIMARY KEY DEFAULT nextval('after_sales_id_seq'),
        adoption_id INTEGER NOT NULL,
        type VARCHAR NOT NULL,
        description TEXT,
        status VARCHAR DEFAULT 'pending',
        resolution TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        FOREIGN KEY (adoption_id) REFERENCES adoptions(id)
    )
    """)
    
    farmer_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'farmer'").fetchone()[0]
    if farmer_count == 0:
        _seed_sample_data(conn)
    
    conn.close()


def _seed_sample_data(conn):
    import bcrypt
    
    def hash_password(password):
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    conn.execute("""
    INSERT INTO users (id, username, email, password_hash, full_name, role, status) VALUES
    (1, 'admin', 'admin@farm.com', ?, '系统管理员', 'admin', 'active'),
    (2, 'farmer_zhang', 'zhang@farm.com', ?, '张大叔', 'farmer', 'active'),
    (3, 'farmer_li', 'li@farm.com', ?, '李阿姨', 'farmer', 'active'),
    (4, 'consumer_wang', 'wang@example.com', ?, '王小明', 'consumer', 'active'),
    (5, 'consumer_chen', 'chen@example.com', ?, '陈小红', 'consumer', 'active')
    """, [
        hash_password("admin123"),
        hash_password("farmer123"),
        hash_password("farmer123"),
        hash_password("consumer123"),
        hash_password("consumer123")
    ])
    
    conn.execute("""
    INSERT INTO plots (id, farmer_id, name, type, area, location, description, status) VALUES
    (1, 2, '张家苹果园', '果园', 50.0, '山东省烟台市', '红富士苹果种植基地，日照充足，口感脆甜。', 'active'),
    (2, 2, '张家茶园', '茶田', 20.0, '浙江省杭州市', '龙井茶园，手工采摘，品质上乘。', 'active'),
    (3, 3, '李家菜园', '菜地', 10.0, '江苏省南京市', '有机蔬菜种植，无农药化肥。', 'active'),
    (4, 3, '李家草莓园', '果园', 5.0, '江苏省南京市', '奶油草莓，新鲜甜美。', 'active')
    """)
    
    conn.execute("""
    INSERT INTO batches (id, plot_id, name, description, price, unit, total_quantity, adopted_quantity, harvest_date, delivery_methods, status) VALUES
    (1, 1, '2024秋季红富士', '秋季成熟的红富士苹果，脆甜多汁', 8.5, '斤', 5000, 1200, '2024-10-15', '自提,快递,配送', 'open'),
    (2, 1, '2024冬季苹果', '晚熟品种，更甜更脆', 9.0, '斤', 3000, 0, '2024-12-01', '自提,快递', 'open'),
    (3, 2, '明前龙井', '清明前采摘的龙井绿茶，清香扑鼻', 200.0, '两', 200, 50, '2024-04-05', '快递', 'closed'),
    (4, 3, '秋季蔬菜套餐', '有机蔬菜组合：白菜、萝卜、菠菜', 30.0, '份', 200, 80, '2024-11-01', '自提,配送', 'open'),
    (5, 4, '冬季草莓', '奶油草莓，冬日限定', 35.0, '斤', 500, 0, '2024-12-20', '自提,配送', 'open')
    """)
    
    conn.execute("""
    INSERT INTO adoptions (id, batch_id, consumer_id, quantity, total_price, pickup_date, delivery_method, delivery_address, status) VALUES
    (1, 1, 4, 20, 170.0, '2024-10-20', '快递', '北京市朝阳区xxx街道123号', 'confirmed'),
    (2, 1, 5, 50, 425.0, '2024-10-18', '自提', NULL, 'confirmed'),
    (3, 3, 4, 2, 400.0, '2024-04-10', '快递', '北京市朝阳区xxx街道123号', 'completed'),
    (4, 4, 5, 5, 150.0, '2024-11-05', '配送', '上海市浦东新区xxx路456号', 'pending')
    """)
    
    conn.execute("""
    INSERT INTO weather_events (id, batch_id, event_type, description, severity, affected_date) VALUES
    (1, 1, '暴雨', '近期连续暴雨，可能影响苹果品质和采摘时间', 'moderate', '2024-10-10')
    """)
    
    conn.execute("""
    INSERT INTO after_sales (id, adoption_id, type, description, status) VALUES
    (1, 1, 'quality', '收到的苹果有部分碰伤', 'resolved'),
    (2, 4, 'delivery', '希望提前配送时间', 'pending')
    """)
    
    for _ in range(5):
        conn.execute("SELECT nextval('users_id_seq')")
    for _ in range(4):
        conn.execute("SELECT nextval('plots_id_seq')")
    for _ in range(5):
        conn.execute("SELECT nextval('batches_id_seq')")
    for _ in range(4):
        conn.execute("SELECT nextval('adoptions_id_seq')")
    for _ in range(1):
        conn.execute("SELECT nextval('weather_events_id_seq')")
    for _ in range(2):
        conn.execute("SELECT nextval('after_sales_id_seq')")
