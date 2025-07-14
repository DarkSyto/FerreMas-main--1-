from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe, httpx, os
from dotenv import load_dotenv

# Inicialización de la aplicación
app = FastAPI(
    title="FERREMAS API",
    description="Proyecto de integración DUOC UC",
    version="1.0.0",
)

# Configuración CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Variables de entorno
load_dotenv()
BASE_API = os.getenv("API_BASE")
TOKEN_GLOBAL = os.getenv("TOKEN_FIJO")
TOKEN_VENDEDOR_OK = os.getenv("TOKEN_VENDEDOR_PERMITIDO")
TOKEN_VENDEDOR_NO = os.getenv("TOKEN_VENDEDOR_DENEGADO")
API_DIVISAS = os.getenv("TOKEN_FXRATESAPI")
stripe.api_key = os.getenv("CLAVE_SECRETA_STRIPE")

# Datos de acceso simulados
CUENTAS_AUTORIZADAS = [
    {"usuario": "javier_thompson", "contrasena": "aONF4d6aNBIxRjlgjBRRzrS", "rol": "admin"},
    {"usuario": "ignacio_tapia", "contrasena": "f7rWChmQS1JYfThT", "rol": "maintainer"},
    {"usuario": "stripe_sa", "contrasena": "dzkQqDL9XZH33YDzhmsf", "rol": "service_account"},
    {"usuario": "Admin", "contrasena": "1234", "rol": "admin"},
]

# Modelos de datos
class ItemPago(BaseModel):
    id: str
    nombre: str
    precio: int
    cantidad: int
    moneda: str

class NuevoProducto(BaseModel):
    nombre: str
    descripcion: str
    precio: int
    categoria: str
    stock: int
    moneda: str

# Autenticación
def auth_token_global(x_authentication: str = Header(None, alias="x-authentication")):
    if x_authentication != TOKEN_GLOBAL:
        raise HTTPException(status_code=403, detail="Token inválido")
    return x_authentication

def auth_token_vendedor(x_vendor_token: str = Header(None, alias="x-vendor-token")):
    if x_vendor_token != TOKEN_VENDEDOR_OK:
        raise HTTPException(status_code=403, detail="Acceso denegado para vendedor")
    return x_vendor_token

# Funciones reutilizables
async def get_from_api(endpoint: str, token: str):
    headers = {"x-authentication": token}
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_API}{endpoint}", headers=headers)
    return JSONResponse(status_code=response.status_code, content=response.json())

async def post_to_api(endpoint: str, body: dict, token: str):
    headers = {"x-authentication": token}
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_API}{endpoint}", json=body, headers=headers)
    return JSONResponse(status_code=response.status_code, content=response.json())

async def put_to_api(endpoint: str, token: str):
    headers = {"x-authentication": token}
    async with httpx.AsyncClient() as client:
        response = await client.put(f"{BASE_API}{endpoint}", headers=headers)
    return JSONResponse(status_code=response.status_code, content=response.json())

# Autenticación simple
@app.post("/login", tags=["Autenticación"])
async def autenticar_usuario(credenciales: dict):
    user = credenciales.get("user")
    password = credenciales.get("password")
    for cuenta in CUENTAS_AUTORIZADAS:
        if cuenta["usuario"] == user and cuenta["contrasena"] == password:
            token_vendedor = TOKEN_VENDEDOR_NO if cuenta["rol"] == "service_account" else TOKEN_VENDEDOR_OK
            return {"token": TOKEN_GLOBAL, "rol": cuenta["rol"], "vendorToken": token_vendedor}
    raise HTTPException(401, "Credenciales inválidas")

# Divisas
@app.get("/fxrate", tags=["Divisas"])
async def obtener_tasa(moneda_base: str = Query(..., min_length=3, max_length=3), destino: str = Query(..., min_length=3, max_length=3)):
    url = f"https://fxratesapi.com/api/latest?base={moneda_base.upper()}&symbols={destino.upper()}&api_key={API_DIVISAS}"
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
    if res.status_code != 200:
        raise HTTPException(502, "No se pudo obtener la tasa de cambio")
    rate = res.json().get("rates", {}).get(destino.upper())
    if rate is None:
        raise HTTPException(400, "Código de moneda no válido")
    return {"rate": rate}

# Stripe
@app.post("/stripe/sesion", tags=["Pagos"])
async def iniciar_pago(productos: list[ItemPago]):
    try:
        line_items = [{
            "price_data": {
                "currency": p.moneda,
                "unit_amount": p.precio,
                "product_data": {"name": p.nombre}
            },
            "quantity": p.cantidad
        } for p in productos]
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=line_items,
            success_url="https://tusitio.com/success",
            cancel_url="https://tusitio.com/cancel"
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/stripe/config", tags=["Pagos"])
async def obtener_clave_publica():
    public_key = os.getenv("CLAVE_PUBLICA_STRIPE")
    if not public_key:
        raise HTTPException(500, "Clave pública no disponible")
    return {"publicKey": public_key}

# Endpoints de productos
@app.get("/articulos", tags=["Artículos"])
async def obtener_articulos(token: str = Depends(auth_token_global)):
    return await get_from_api("/data/articulos", token)

@app.get("/articulos/{id}", tags=["Artículos"])
async def articulo_por_id(id: str, token: str = Depends(auth_token_global)):
    return await get_from_api(f"/data/articulos/{id}", token)

@app.post("/articulos", tags=["Artículos"])
async def crear_articulo(nuevo: NuevoProducto, token: str = Depends(auth_token_global)):
    return await post_to_api("/data/articulos", nuevo.dict(), token)

@app.get("/articulos/novedades", tags=["Artículos"])
async def novedades(token: str = Depends(auth_token_global)):
    return await get_from_api("/data/articulos/novedades", token)

@app.get("/articulos/promociones", tags=["Artículos"])
async def promociones(token: str = Depends(auth_token_global)):
    return await get_from_api("/data/articulos/promociones", token)

@app.put("/articulos/venta/{id}", tags=["Ventas"])
async def vender_articulo(id: str, cantidad: int = Query(...), token: str = Depends(auth_token_global)):
    return await put_to_api(f"/data/articulos/venta/{id}?cantidad={cantidad}", token)

# Sucursales
@app.get("/sucursales", tags=["Sucursales"])
async def listar_sucursales(token: str = Depends(auth_token_global)):
    return await get_from_api("/data/sucursales", token)

@app.get("/sucursales/{id}", tags=["Sucursales"])
async def sucursal_por_id(id: str, token: str = Depends(auth_token_global)):
    return await get_from_api(f"/data/sucursales/{id}", token)

# Vendedores
@app.get("/vendedores", tags=["Vendedores"])
async def vendedores(token: str = Depends(auth_token_global), vtoken: str = Depends(auth_token_vendedor)):
    return await get_from_api("/data/vendedores", token)

@app.get("/vendedores/{id}", tags=["Vendedores"])
async def vendedor_por_id(id: str, token: str = Depends(auth_token_global), vtoken: str = Depends(auth_token_vendedor)):
    return await get_from_api(f"/data/vendedores/{id}", token)

@app.get("/vendedores/porSucursal", tags=["Vendedores"])
async def vendedores_por_sucursal(sucursal_Id: str = Query(...), token: str = Depends(auth_token_global), vtoken: str = Depends(auth_token_vendedor)):
    return await get_from_api(f"/data/vendedores?sucursalId={sucursal_Id}", token)

# Pedidos
@app.post("/pedidos/nuevo", tags=["Pedidos"])
async def nuevo_pedido(pedido: dict, token: str = Depends(auth_token_global)):
    return await post_to_api("/data/pedidos/nuevo", pedido, token)

# Contacto
@app.post("/contacto/vendedor", tags=["Contacto"])
async def contacto_via_form(mensaje: dict, token: str = Depends(auth_token_global)):
    return await post_to_api("/data/contacto/vendedor", mensaje, token)
