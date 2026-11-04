from __future__ import annotations

import base64
from dotenv import load_dotenv
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
import httpx
from jose import JWTError, jwt
from openai import OpenAI
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, func, or_, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pj_catalogue.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True)
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "jewellery_images")
USE_SUPABASE_STORAGE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
SECRET_KEY = os.getenv("APP_SECRET_KEY", "development-only-change-this-secret")
ALGORITHM = "HS256"
TOKEN_MINUTES = 60 * 8
MAX_IMAGE_MB = int(os.getenv("MAX_IMAGE_MB", "8"))
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

class Base(DeclarativeBase):
    pass

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    description: Mapped[str] = mapped_column(String(300), default="")
    products: Mapped[list["Product"]] = relationship(back_populates="category")

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("categories.id"), nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    tags: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    category: Mapped[Optional[Category]] = relationship(back_populates="products")

if DATABASE_URL.startswith("sqlite"):
    Base.metadata.create_all(engine)

app = FastAPI(title="PJ Jewellery Catalogue API", version="1.0.0", description="Single-brand jewellery catalogue assessment prototype")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if UPLOAD_DIR.exists():
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

class LoginInput(BaseModel):
    username: str
    password: str

class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)

class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    description: str = ""
    category_id: Optional[int] = None
    tags: list[str] = []
    status: str = "draft"

class AIRequest(BaseModel):
    image_path: str

class ProductUpdate(BaseModel):
    sku: Optional[str] = Field(default=None, max_length=40)
    title: Optional[str] = Field(default=None, max_length=160)
    description: Optional[str] = None
    category_id: Optional[int] = None
    tags: Optional[list[str]] = None
    image_path: Optional[str] = None
    status: Optional[str] = None
    archived: Optional[bool] = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": username, "iat": now, "exp": now + timedelta(minutes=TOKEN_MINUTES)}, SECRET_KEY, algorithm=ALGORITHM)


def require_admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Administrator sign-in required")
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username != os.getenv("ADMIN_USERNAME", "admin"):
            raise HTTPException(status_code=401, detail="Invalid administrator token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired or token invalid")


def product_json(p: Product) -> dict:
    return {
        "id": p.id, "sku": p.sku, "title": p.title, "description": p.description,
        "category_id": p.category_id, "category": p.category.name if p.category else "Uncategorised",
        "image_url": (p.image_path if p.image_path and p.image_path.startswith(("http://", "https://")) else f"/uploads/{p.image_path}") if p.image_path else None,
        "tags": [x for x in p.tags.split(",") if x], "status": p.status,
        "archived": p.archived, "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def ensure_seed_categories(db: Session):
    category_descriptions = {
        "Rings": "Everyday bands, solitaires and statement rings",
        "Necklaces": "Pendants, chains and layered necklaces",
        "Earrings": "Studs, hoops and statement drops",
        "Bracelets": "Delicate chains and statement bracelets",
        "Bangles": "Classic, textured and stackable bangles",
        "Chains": "Fine and statement jewellery chains",
        "Pendants": "Meaningful motifs and polished pendants",
        "Anklets": "Delicate everyday and occasion anklets",
    }
    existing = {c.name.lower(): c for c in db.scalars(select(Category)).all()}
    for name, description in category_descriptions.items():
        if name.lower() not in existing:
            db.add(Category(name=name, description=description))
    db.commit()
    if (db.scalar(select(func.count(Product.id))) or 0) > 0:
        return
    categories = {c.name: c.id for c in db.scalars(select(Category)).all()}
    seed_rows = [
        ("PJ-0001", "Solitaire Ring", "A thoughtfully styled solitaire ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-001.svg"),
        ("PJ-0002", "Twist Band Ring", "A thoughtfully styled twist band ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-002.svg"),
        ("PJ-0003", "Halo Ring", "A thoughtfully styled halo ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-003.svg"),
        ("PJ-0004", "Floral Cocktail Ring", "A thoughtfully styled floral cocktail ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-004.svg"),
        ("PJ-0005", "Eternity Band", "A thoughtfully styled eternity band from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-005.svg"),
        ("PJ-0006", "Pearl Accent Ring", "A thoughtfully styled pearl accent ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-006.svg"),
        ("PJ-0007", "Marquise Ring", "A thoughtfully styled marquise ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-007.svg"),
        ("PJ-0008", "Open Cuff Ring", "A thoughtfully styled open cuff ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-008.svg"),
        ("PJ-0009", "Vintage Signet Ring", "A thoughtfully styled vintage signet ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-009.svg"),
        ("PJ-0010", "Duo Stone Ring", "A thoughtfully styled duo stone ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-010.svg"),
        ("PJ-0011", "Celestial Ring", "A thoughtfully styled celestial ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-011.svg"),
        ("PJ-0012", "Petal Promise Ring", "A thoughtfully styled petal promise ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-012.svg"),
        ("PJ-0013", "Classic Dome Ring", "A thoughtfully styled classic dome ring from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-013.svg"),
        ("PJ-0014", "Dainty Pendant Necklace", "A thoughtfully styled dainty pendant necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-014.svg"),
        ("PJ-0015", "Layered Chain Necklace", "A thoughtfully styled layered chain necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-015.svg"),
        ("PJ-0016", "Pearl Drop Necklace", "A thoughtfully styled pearl drop necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-016.svg"),
        ("PJ-0017", "Celestial Charm Necklace", "A thoughtfully styled celestial charm necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-017.svg"),
        ("PJ-0018", "Heart Locket Necklace", "A thoughtfully styled heart locket necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-018.svg"),
        ("PJ-0019", "Floral Pendant Necklace", "A thoughtfully styled floral pendant necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-019.svg"),
        ("PJ-0020", "Station Necklace", "A thoughtfully styled station necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-020.svg"),
        ("PJ-0021", "Beaded Collar Necklace", "A thoughtfully styled beaded collar necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-021.svg"),
        ("PJ-0022", "Teardrop Pendant", "A thoughtfully styled teardrop pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-022.svg"),
        ("PJ-0023", "Minimal Bar Necklace", "A thoughtfully styled minimal bar necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-023.svg"),
        ("PJ-0024", "Heritage Coin Necklace", "A thoughtfully styled heritage coin necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-024.svg"),
        ("PJ-0025", "Halo Pendant Necklace", "A thoughtfully styled halo pendant necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-025.svg"),
        ("PJ-0026", "Sculpted Collar Necklace", "A thoughtfully styled sculpted collar necklace from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-026.svg"),
        ("PJ-0027", "Classic Stud Earrings", "A thoughtfully styled classic stud earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-027.svg"),
        ("PJ-0028", "Mini Hoop Earrings", "A thoughtfully styled mini hoop earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-028.svg"),
        ("PJ-0029", "Pearl Drop Earrings", "A thoughtfully styled pearl drop earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-029.svg"),
        ("PJ-0030", "Floral Cluster Studs", "A thoughtfully styled floral cluster studs from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-030.svg"),
        ("PJ-0031", "Twisted Huggie Earrings", "A thoughtfully styled twisted huggie earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-031.svg"),
        ("PJ-0032", "Teardrop Earrings", "A thoughtfully styled teardrop earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-032.svg"),
        ("PJ-0033", "Celestial Ear Cuffs", "A thoughtfully styled celestial ear cuffs from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-033.svg"),
        ("PJ-0034", "Geometric Drop Earrings", "A thoughtfully styled geometric drop earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-034.svg"),
        ("PJ-0035", "Daisy Stud Earrings", "A thoughtfully styled daisy stud earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-035.svg"),
        ("PJ-0036", "Statement Chandeliers", "A thoughtfully styled statement chandeliers from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-036.svg"),
        ("PJ-0037", "Oval Halo Earrings", "A thoughtfully styled oval halo earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-037.svg"),
        ("PJ-0038", "Sculpted Dome Studs", "A thoughtfully styled sculpted dome studs from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-038.svg"),
        ("PJ-0039", "Leaf Drop Earrings", "A thoughtfully styled leaf drop earrings from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-039.svg"),
        ("PJ-0040", "Slim Chain Bracelet", "A thoughtfully styled slim chain bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-040.svg"),
        ("PJ-0041", "Tennis Bracelet", "A thoughtfully styled tennis bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-041.svg"),
        ("PJ-0042", "Charm Bracelet", "A thoughtfully styled charm bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-042.svg"),
        ("PJ-0043", "Pearl Bracelet", "A thoughtfully styled pearl bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-043.svg"),
        ("PJ-0044", "Twist Bangle", "A thoughtfully styled twist bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-044.svg"),
        ("PJ-0045", "Open Cuff Bracelet", "A thoughtfully styled open cuff bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-045.svg"),
        ("PJ-0046", "Station Bracelet", "A thoughtfully styled station bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-046.svg"),
        ("PJ-0047", "Heart Link Bracelet", "A thoughtfully styled heart link bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-047.svg"),
        ("PJ-0048", "Beaded Bracelet", "A thoughtfully styled beaded bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-048.svg"),
        ("PJ-0049", "Sculpted Cuff", "A thoughtfully styled sculpted cuff from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-049.svg"),
        ("PJ-0050", "Celestial Bracelet", "A thoughtfully styled celestial bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-050.svg"),
        ("PJ-0051", "Petal Chain Bracelet", "A thoughtfully styled petal chain bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-051.svg"),
        ("PJ-0052", "Classic Link Bracelet", "A thoughtfully styled classic link bracelet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-052.svg"),
        ("PJ-0053", "Classic Gold Bangle", "A thoughtfully styled classic gold bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-053.svg"),
        ("PJ-0054", "Textured Bangle", "A thoughtfully styled textured bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-054.svg"),
        ("PJ-0055", "Open Oval Bangle", "A thoughtfully styled open oval bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-055.svg"),
        ("PJ-0056", "Engraved Bangle", "A thoughtfully styled engraved bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-056.svg"),
        ("PJ-0057", "Twisted Rope Bangle", "A thoughtfully styled twisted rope bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-057.svg"),
        ("PJ-0058", "Slim Stackable Bangle", "A thoughtfully styled slim stackable bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-058.svg"),
        ("PJ-0059", "Floral Kada", "A thoughtfully styled floral kada from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-059.svg"),
        ("PJ-0060", "Polished Dome Kada", "A thoughtfully styled polished dome kada from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-060.svg"),
        ("PJ-0061", "Heritage Bangle", "A thoughtfully styled heritage bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-061.svg"),
        ("PJ-0062", "Double Line Bangle", "A thoughtfully styled double line bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-062.svg"),
        ("PJ-0063", "Beaded Edge Bangle", "A thoughtfully styled beaded edge bangle from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-063.svg"),
        ("PJ-0064", "Sculpted Kada", "A thoughtfully styled sculpted kada from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bangles", "bangles, atelier pj, jewellery, giftable, gold-tone", "catalogue-064.svg"),
        ("PJ-0065", "Fine Cable Chain", "A thoughtfully styled fine cable chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-065.svg"),
        ("PJ-0066", "Rope Chain", "A thoughtfully styled rope chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-066.svg"),
        ("PJ-0067", "Singapore Chain", "A thoughtfully styled singapore chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-067.svg"),
        ("PJ-0068", "Box Chain", "A thoughtfully styled box chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-068.svg"),
        ("PJ-0069", "Figaro Chain", "A thoughtfully styled figaro chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-069.svg"),
        ("PJ-0070", "Curb Chain", "A thoughtfully styled curb chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-070.svg"),
        ("PJ-0071", "Paperclip Chain", "A thoughtfully styled paperclip chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-071.svg"),
        ("PJ-0072", "Bead Chain", "A thoughtfully styled bead chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-072.svg"),
        ("PJ-0073", "Twisted Link Chain", "A thoughtfully styled twisted link chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-073.svg"),
        ("PJ-0074", "Venetian Chain", "A thoughtfully styled venetian chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-074.svg"),
        ("PJ-0075", "Anchor Chain", "A thoughtfully styled anchor chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-075.svg"),
        ("PJ-0076", "Oval Link Chain", "A thoughtfully styled oval link chain from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Chains", "chains, atelier pj, jewellery, giftable, gold-tone", "catalogue-076.svg"),
        ("PJ-0077", "Solitaire Pendant", "A thoughtfully styled solitaire pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-077.svg"),
        ("PJ-0078", "Pearl Pendant", "A thoughtfully styled pearl pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-078.svg"),
        ("PJ-0079", "Heart Pendant", "A thoughtfully styled heart pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-079.svg"),
        ("PJ-0080", "Initial Pendant", "A thoughtfully styled initial pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-080.svg"),
        ("PJ-0081", "Evil Eye Pendant", "A thoughtfully styled evil eye pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-081.svg"),
        ("PJ-0082", "Floral Pendant", "A thoughtfully styled floral pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-082.svg"),
        ("PJ-0083", "Starburst Pendant", "A thoughtfully styled starburst pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-083.svg"),
        ("PJ-0084", "Teardrop Pendant", "A thoughtfully styled teardrop pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-084.svg"),
        ("PJ-0085", "Coin Pendant", "A thoughtfully styled coin pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-085.svg"),
        ("PJ-0086", "Moon Pendant", "A thoughtfully styled moon pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-086.svg"),
        ("PJ-0087", "Lotus Pendant", "A thoughtfully styled lotus pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-087.svg"),
        ("PJ-0088", "Infinity Pendant", "A thoughtfully styled infinity pendant from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Pendants", "pendants, atelier pj, jewellery, giftable, gold-tone", "catalogue-088.svg"),
        ("PJ-0089", "Dainty Chain Anklet", "A thoughtfully styled dainty chain anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-089.svg"),
        ("PJ-0090", "Beaded Anklet", "A thoughtfully styled beaded anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-090.svg"),
        ("PJ-0091", "Charm Anklet", "A thoughtfully styled charm anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-091.svg"),
        ("PJ-0092", "Pearl Anklet", "A thoughtfully styled pearl anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-092.svg"),
        ("PJ-0093", "Double Layer Anklet", "A thoughtfully styled double layer anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-093.svg"),
        ("PJ-0094", "Star Charm Anklet", "A thoughtfully styled star charm anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-094.svg"),
        ("PJ-0095", "Minimal Link Anklet", "A thoughtfully styled minimal link anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-095.svg"),
        ("PJ-0096", "Floral Anklet", "A thoughtfully styled floral anklet from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Anklets", "anklets, atelier pj, jewellery, giftable, gold-tone", "catalogue-096.svg"),
        ("PJ-0097", "Luminous Ring Design", "A thoughtfully styled luminous ring design from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Rings", "rings, atelier pj, jewellery, giftable, gold-tone", "catalogue-097.svg"),
        ("PJ-0098", "Aurora Necklace Design", "A thoughtfully styled aurora necklace design from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Necklaces", "necklaces, atelier pj, jewellery, giftable, gold-tone", "catalogue-098.svg"),
        ("PJ-0099", "Muse Earring Design", "A thoughtfully styled muse earring design from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Earrings", "earrings, atelier pj, jewellery, giftable, gold-tone", "catalogue-099.svg"),
        ("PJ-0100", "Serene Bracelet Design", "A thoughtfully styled serene bracelet design from the Atelier PJ collection. Its refined silhouette and luminous finish make it an elegant choice for everyday wear and special moments.", "Bracelets", "bracelets, atelier pj, jewellery, giftable, gold-tone", "catalogue-100.svg"),
    ]
    for sku, title, description, category_name, tags, image_file in seed_rows:
        db.add(Product(sku=sku, title=title, description=description,
                       category_id=categories[category_name], tags=tags,
                       image_path=image_file, status="published", archived=False))
    db.commit()

@app.on_event("startup")
def startup():
    # Production schema and the original 800-product catalogue are migrated once
    # with the supplied migration script. Never seed or rewrite production data
    # during a serverless cold start.
    if DATABASE_URL.startswith("sqlite"):
        with SessionLocal() as db:
            ensure_seed_categories(db)
        from expand_catalogue import expand_to_800
        expand_to_800()
        from assign_unique_images import assign_unique_product_images
        assign_unique_product_images()

@app.get("/", response_class=HTMLResponse)
def home():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "PJ Jewellery Catalogue"}

@app.post("/api/auth/login")
def login(payload: LoginInput):
    expected_user = os.getenv("ADMIN_USERNAME", "admin")
    expected_password = os.getenv("ADMIN_PASSWORD", "change-this-password")
    if not secrets.compare_digest(payload.username, expected_user) or not secrets.compare_digest(payload.password, expected_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"access_token": create_token(payload.username), "token_type": "bearer", "expires_in": TOKEN_MINUTES * 60}

@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)):
    ensure_seed_categories(db)
    rows = db.scalars(select(Category).order_by(Category.name)).all()
    return [{"id": c.id, "name": c.name, "description": c.description, "product_count": len(c.products)} for c in rows]

@app.post("/api/categories", dependencies=[Depends(require_admin)])
def create_category(payload: CategoryInput, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Category name is required")
    if db.scalar(select(Category).where(func.lower(Category.name) == name.lower())):
        raise HTTPException(409, "A category with that name already exists")
    c = Category(name=name, description=payload.description.strip())
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "name": c.name, "description": c.description, "product_count": 0}

@app.put("/api/categories/{category_id}", dependencies=[Depends(require_admin)])
def update_category(category_id: int, payload: CategoryInput, db: Session = Depends(get_db)):
    c = db.get(Category, category_id)
    if not c: raise HTTPException(404, "Category not found")
    name = payload.name.strip()
    conflict = db.scalar(select(Category).where(func.lower(Category.name) == name.lower(), Category.id != category_id))
    if conflict: raise HTTPException(409, "A category with that name already exists")
    c.name = name; c.description = payload.description.strip(); db.commit(); db.refresh(c)
    return {"id": c.id, "name": c.name, "description": c.description, "product_count": len(c.products)}

@app.get("/api/products")
def list_products(q: str = "", category_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(Product).join(Category, isouter=True).order_by(Product.created_at.desc())
    stmt = stmt.where(Product.status == "published", Product.archived.is_(False))
    if category_id: stmt = stmt.where(Product.category_id == category_id)
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.title.ilike(term), Product.description.ilike(term), Product.sku.ilike(term), Product.tags.ilike(term)))
    return [product_json(p) for p in db.scalars(stmt).unique().all()]

@app.get("/api/products/{product_id}")
def get_product(product_id: int, admin: Optional[str] = Depends(lambda: None), db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p or p.archived or p.status != "published": raise HTTPException(404, "Product not found")
    return product_json(p)

@app.get("/api/admin/products", dependencies=[Depends(require_admin)])
def admin_products(db: Session = Depends(get_db)):
    rows = db.scalars(select(Product).order_by(Product.created_at.desc())).all()
    return [product_json(p) for p in rows]

@app.get("/api/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats(db: Session = Depends(get_db)):
    products = db.scalars(select(Product)).all()
    categories = db.scalar(select(func.count(Category.id))) or 0
    return {"total_products": len(products), "published": sum(p.status == "published" and not p.archived for p in products), "drafts": sum(p.status != "published" and not p.archived for p in products), "archived": sum(p.archived for p in products), "categories": categories}


@app.post("/api/uploads", dependencies=[Depends(require_admin)])

async def upload_image(
    file: UploadFile = File(...),
    category: str = Form("uncategorised")
):
    allowed_categories = {
        "rings", "necklaces", "earrings", "bracelets",
        "bangles", "chains", "pendants", "anklets",
        "uncategorised"
    }

    category = category.strip().lower()
    print("UPLOAD DEBUG - Category received:", category)
    print("UPLOAD DEBUG - Upload directory:", UPLOAD_DIR / category)

    if category not in allowed_categories:
        raise HTTPException(400, "Invalid image category")

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            415, "Unsupported image type. Use JPG, PNG, WEBP or GIF."
        )

    content = await file.read()

    if not content:
        raise HTTPException(400, "The uploaded file is empty")

    if len(content) > MAX_IMAGE_MB * 1024 * 1024:
        raise HTTPException(
            413, f"Image exceeds the {MAX_IMAGE_MB} MB limit"
        )

    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif"
    }[file.content_type]

    filename = f"{secrets.token_hex(16)}{suffix}"

    object_path = f"{category}/{filename}"

    if USE_SUPABASE_STORAGE:
        endpoint = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{object_path}"
        headers = {
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Content-Type": file.content_type,
            "x-upsert": "false",
        }
        try:
            response = httpx.post(endpoint, headers=headers, content=content, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Image storage upload failed. Please retry.") from exc
        image_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{object_path}"
        return {"image_path": image_url, "image_url": image_url}

    category_dir = UPLOAD_DIR / category
    category_dir.mkdir(parents=True, exist_ok=True)
    (category_dir / filename).write_bytes(content)
    return {"image_path": object_path, "image_url": f"/uploads/{object_path}"}

@app.post("/api/ai/suggest", dependencies=[Depends(require_admin)])
def ai_suggest(payload: AIRequest):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        raise HTTPException(
            503,
            "AI is not configured. Add OPENAI_API_KEY to your .env file and restart the app."
        )

    image_path = payload.image_path.strip().replace("\\", "/")
    if image_path.startswith(("http://", "https://")):
        expected_prefix = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/"
        if not SUPABASE_URL or not image_path.startswith(expected_prefix):
            raise HTTPException(400, "Image URL is not from the configured catalogue storage")
        try:
            image_response = httpx.get(image_path, timeout=20.0, follow_redirects=True)
            image_response.raise_for_status()
            image_bytes = image_response.content
        except httpx.HTTPError as exc:
            raise HTTPException(404, "Stored image could not be retrieved") from exc
        ext = Path(image_path.split("?", 1)[0]).suffix.lower()
    else:
        if image_path.startswith("/") or ".." in Path(image_path).parts:
            raise HTTPException(400, "Invalid image path")
        image_file = (UPLOAD_DIR / image_path).resolve()
        if not image_file.is_relative_to(UPLOAD_DIR.resolve()):
            raise HTTPException(400, "Invalid image path")
        if not image_file.is_file():
            raise HTTPException(404, "Uploaded image not found. Upload the image again.")
        ext = image_file.suffix.lower()
        image_bytes = image_file.read_bytes()

    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}.get(ext)
    if not mime:
        raise HTTPException(415, "Unsupported image format")
    image_data = base64.b64encode(image_bytes).decode("ascii")

    client = OpenAI(api_key=api_key)

    prompt = ("Inspect this jewellery product image and return ONLY valid JSON with keys title, description, category, tags. "
              "Use a concise premium catalogue title, a neutral visual description, one category from Rings, Necklaces, Earrings, Bracelets, Other, "
              "and 4-8 relevant design/search tags. Do not claim exact metal, gold purity, gemstone authenticity, weight, or material composition "
              "unless visibly and unambiguously printed in the image. Describe only observable visual characteristics. JSON values: title string, description string, category string, tags array of strings.")

    try:
        response = client.responses.create(
            model=os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini"),
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": f"data:{mime};base64,{image_data}"}]}],
        )

        raw = response.output_text.strip()

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)

        required = {"title", "description", "category", "tags"}

        if not required.issubset(data) or not isinstance(data["tags"], list):
            raise ValueError("Missing fields")

        return {
            "title": str(data["title"])[:160],
            "description": str(data["description"]),
            "category": str(data["category"]),
            "tags": [str(t)[:50] for t in data["tags"][:10]],
            "provider": "OpenAI",
            "model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            502,
            "AI suggestion failed. Check the API key/model, then retry."
        ) from exc

@app.post("/api/admin/products", dependencies=[Depends(require_admin)])
def create_product_admin(payload: dict, db: Session = Depends(get_db)):
    try:
        data = ProductInput.model_validate(payload)
    except Exception as exc:
        raise HTTPException(422, "Invalid product fields") from exc

    image_path = payload.get("image_path")

    if data.status not in {"draft", "published"}:
        raise HTTPException(422, "Status must be draft or published")

    if db.scalar(select(Product).where(Product.sku == data.sku.strip())):
        raise HTTPException(409, "SKU already exists")

    if data.category_id and not db.get(Category, data.category_id):
        raise HTTPException(422, "Invalid category")

    if image_path:
        image_path = image_path.replace("\\\\", "/")

        if image_path.startswith(("http://", "https://")):
            expected_prefix = (
                f"{SUPABASE_URL}/storage/v1/object/public/"
                f"{SUPABASE_BUCKET}/"
            )
            if not SUPABASE_URL or not image_path.startswith(expected_prefix):
                raise HTTPException(400, "Invalid image URL")
        elif image_path.startswith("/") or ".." in Path(image_path).parts:
            raise HTTPException(400, "Invalid image path")

    p = Product(
        sku=data.sku.strip(),
        title=data.title.strip(),
        description=data.description.strip(),
        category_id=data.category_id,
        tags=",".join(t.strip() for t in data.tags if t.strip()),
        status=data.status,
        image_path=image_path
    )

    db.add(p)
    db.commit()
    db.refresh(p)

    return product_json(p)


@app.patch("/api/admin/products/{product_id}", dependencies=[Depends(require_admin)])

def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "Product not found")

    data = payload.model_dump(exclude_unset=True)

    if "status" in data and data["status"] not in {"draft", "published"}:
        raise HTTPException(422, "Status must be draft or published")

    if "category_id" in data and data["category_id"] is not None and not db.get(Category, data["category_id"]):
        raise HTTPException(422, "Invalid category")

    if "sku" in data and data["sku"]:
        duplicate = db.scalar(
            select(Product).where(
                Product.sku == data["sku"],
                Product.id != p.id
            )
        )
        if duplicate:
            raise HTTPException(409, "SKU already exists")

    for key, value in data.items():
        if key == "tags":
            value = ",".join(t.strip() for t in value if t.strip())

        if key == "image_path":
            value = value.replace("\\\\", "/") if value else None

            if value and value.startswith(("http://", "https://")):
                expected_prefix = (
                    f"{SUPABASE_URL}/storage/v1/object/public/"
                    f"{SUPABASE_BUCKET}/"
                )
                if not SUPABASE_URL or not value.startswith(expected_prefix):
                    raise HTTPException(400, "Invalid image URL")

            elif value and (
                value.startswith("/")
                or ".." in Path(value).parts
            ):
                raise HTTPException(400, "Invalid image path")

        setattr(p, key, value)

    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)

    return product_json(p)



@app.delete("/api/admin/products/{product_id}", dependencies=[Depends(require_admin)])
def archive_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p: raise HTTPException(404, "Product not found")
    p.archived = True; p.status = "draft"; db.commit()
    return {"ok": True, "message": "Product archived"}
