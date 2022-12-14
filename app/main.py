from datetime import timedelta

from fastapi.encoders import jsonable_encoder

from app import maingamefile, users, lib, my_message
from fastapi import FastAPI, Request, Response, Depends, Form, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, HTMLResponse, PlainTextResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi_login import LoginManager
from starlette import status as stss
from pathlib import Path
from json import dumps

from app.flash import flash, get_flashed_messages

socketmanager = my_message.SocketManager()
class NotAuthenticatedException(Exception):
    pass


middleware = [
    Middleware(SessionMiddleware,
               secret_key="sajdnflkajsndkjfnaskdnfsdzcllasdfkjnlsjkdfngbsldfgbsldqwertyuiopasdfghjklzxcvbnmpolikmujnyhbtgvrfcedxwszqa")
]

app = FastAPI(middleware=middleware)
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
secret = "sajdnflkajsndkjfnaskdnfsdzcllasdfkjnlsjkdfngbsldfgbsldqwertyuiopasdfghjklzxcvbnmpolikmujnyhbtgvrfcedxwszqa"
manager = LoginManager(secret, token_url='/auth/token', use_cookie=True, default_expiry=timedelta(hours=72))
manager.not_authenticated_exception = NotAuthenticatedException
manager.cookie_name = "auth-key-for-cc-space"
templates.env.globals['get_flashed_messages'] = get_flashed_messages
manager.useRequest(app)


@app.exception_handler(StarletteHTTPException)
async def custom_exception_handler(request: Request, exc: StarletteHTTPException):
    return templates.TemplateResponse("error.html", {"request": request, "error": str(exc.status_code)},
                                      status_code=exc.status_code)


@app.exception_handler(NotAuthenticatedException)
def auth_exception_handler(request: Request, exc: NotAuthenticatedException):
    """
    Redirect the user to the login page if not logged in
    """
    return RedirectResponse(url='/auth/login')


@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@manager.user_loader()
async def load_user(username: str):
    user = users.get_user(f"{str(username)}")
    print(user)
    return user


@app.get("/auth/login")
async def login(request: Request):
    return templates.TemplateResponse("login.html", {"webname": "login", "request": request})


@app.get("/auth/signup", response_class=HTMLResponse)
async def signup(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request})


@app.post("/auth/login")
async def login(request: Request, data: OAuth2PasswordRequestForm = Depends()):
    username = data.username
    password = data.password
    user = await load_user(username)
    if not user:
        flash(request, "The Username or password you have entered is incorrect", "danger")
        print("not user")
        return templates.TemplateResponse("login.html", {"request": request})
    key = users.password(str(password), user)
    print(user["key"])
    print(key)
    if key != user["key"]:
        flash(request, "The Username or password you have entered is incorrect", "danger")
        print("incorrect password")
        return templates.TemplateResponse("login.html", {"request": request})
    access_token = manager.create_access_token(
        data={"sub": username}
    )
    resp = RedirectResponse(url="/dashboard", status_code=stss.HTTP_302_FOUND)
    manager.set_cookie(resp, access_token)
    return resp


@app.post("/auth/signup")
async def signup(request: Request, username: str = Form("username"), password: str = Form("password"),
                 name: str = Form("name"), email: str = Form("email"), cpassword: str = Form("cpassword"),
                 tos: str = Form("tos")):
    if password == cpassword:
        check = users.checkuser(username, password, email)
        if str(check) == "good":
            users.createuser(username, password, name, tos, email)
            at = manager.create_access_token(
                data={"sub": username}
            )
            resp = RedirectResponse(url="/dashboard", status_code=stss.HTTP_302_FOUND)
            manager.set_cookie(resp, at)
            return resp
        else:
            flash(request, str(check))
            return templates.TemplateResponse("signup.html", {"request": request})
    else:
        flash(request, "Passwords do not match")
        return templates.TemplateResponse("signup.html", {"request": request})


@app.get("/logout")
async def logout():
    responce = RedirectResponse("/auth/login")
    responce.delete_cookie("auth-key-for-cc-space")
    return responce


@app.get("/dashboard", )
async def dashboard(request: Request, user=Depends(manager)):
    gamestats = maingamefile.getstats(user)
    return templates.TemplateResponse("dashboard.html", {"webname": "Dashboard", "request": request, "user": user, "stats": gamestats})


@app.get("/level/{level}")
async def level(request: Request, level, user=Depends(manager)):
    code = Path(f"app/python-levels/{level}.py").read_text()
    out = code.splitlines()
    output = '\n'.join((line) for line in out)
    levelname = lib.n2w(n=level).lower()
    levelnum = level
    print(output)
    message = Path(f"app/python-levels/{level}.message").read_text()
    return templates.TemplateResponse("level.html",
                                      {"webname": f"Level {level}",
                                       "request": request,
                                       "user": user,
                                       "code": code,
                                       "message": message,
                                       "output": output,
                                       "levelname": levelname,
                                       "levelnum": levelnum
                                       })


@app.websocket("/level/{levelname}/{levelnum}")
async def level(websocket: WebSocket, levelname: str, levelnum: str):
    token = websocket.cookies.get('auth-key-for-cc-space')
    user = await manager.get_current_user(token=token)
    if user:
        await websocket.accept()
        complete = False
        while not complete:
            data = await websocket.receive_text()
            answer = maingamefile.check(level=levelnum, code=data)
            if answer:
                send = {"type": "good", "message": "Congratulations you have beaten this level!"}
                send = dumps(send)
                print(send)
                maingamefile.addwin(levelname, user)
                await websocket.send_text(send)
            else:
                send = {"type": "bad", "message": "Incorrect, please try again"}
                send = dumps(send)
                print(send)
                await websocket.send_text(send)


@app.websocket("/api/chat/{username}")
async def chat(websocket: WebSocket, username: str):
    token = websocket.cookies.get('auth-key-for-cc-space')
    print(token)
    user = await manager.get_current_user(token=token)
    print(user)
    if user:
        username = username
        await socketmanager.connect(websocket, username)
        try:
            while True:
                data = await websocket.receive_json()
                await socketmanager.broadcast(data)
        except WebSocketDisconnect:
            socketmanager.disconnect(websocket, username)