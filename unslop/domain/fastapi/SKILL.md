---
name: fastapi-domain
description: Use when generating code for FastAPI applications. Provides generation priors for dependency injection, schema enforcement, and async patterns.
version: 0.1.0
---

# FastAPI Generation Priors

When generating code for a FastAPI application, follow these conventions in addition to the file spec and project principles.

---

## 1. Dependency Injection

Always use `Annotated[T, Depends(...)]` (PEP 593 style). Never use the legacy default-parameter form.

**Do this:**

```python
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db():
    async with async_session() as session:
        yield session

DbSession = Annotated[AsyncSession, Depends(get_db)]

@app.get("/users")
async def list_users(db: DbSession):
    ...
```

**Never generate this:**

```python
# DON'T: legacy dependency injection
@app.get("/users")
async def list_users(db: AsyncSession = Depends(get_db)):
    ...
```

The `Annotated` form is composable, IDE-friendly, and aligns with current FastAPI documentation. The legacy form is not generated under any circumstance.

---

## 2. Schema Enforcement

Three non-negotiables:

1. Endpoints returning JSON should define `response_model`. Endpoints that return non-JSON responses (`FileResponse`, `StreamingResponse`, `Response` with status 204, etc.) should NOT use `response_model` — the response type itself is the schema.
2. Request bodies use Pydantic `BaseModel` subclasses — never raw `dict`.
3. Response schemas are separate from database models — do not expose ORM objects directly.

**Spec-to-code mapping:**

Spec says: "Returns a list of users with id, name, and email."

Generated code defines:

```python
class UserResponse(BaseModel):
    id: int
    name: str
    email: str

@app.get("/users", response_model=list[UserResponse])
async def list_users(db: DbSession) -> list[UserResponse]:
    ...
```

If the spec does not name the response fields, infer a minimal schema from context. If the spec is genuinely ambiguous about response shape, flag it in Phase 0b — do not silently omit `response_model` for JSON-returning endpoints.

---

## 3. Async Patterns

- Use `async def` for routes that call libraries supporting `await` (async SQLAlchemy, httpx, aiofiles, etc.).
- Use plain `def` for routes that call synchronous/blocking libraries (sync SQLAlchemy, `requests`, `subprocess`). FastAPI automatically runs `def` handlers in an external threadpool — do NOT wrap blocking calls in `run_in_executor` inside an `async def` handler; that pattern blocks the event loop while holding the threadpool slot.
- Use `BackgroundTasks` for non-blocking side effects (email, webhooks, audit logs). Do not fire-and-forget with `asyncio.create_task` unless the spec requires it.
- Never use `time.sleep()` in an `async def` route. Use `await asyncio.sleep()` if a delay is needed.

```python
# BackgroundTasks for side effects
from fastapi import BackgroundTasks

@app.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: DbSession,
    tasks: BackgroundTasks,
) -> UserResponse:
    user = await db.create(body)
    tasks.add_task(send_welcome_email, user.email)
    return UserResponse.model_validate(user)
```

---

## 4. Spec Example

The following shows the correct spec register for a FastAPI endpoint and the generated code that satisfies it.

**Spec (intent, not implementation):**

```markdown
## Behavior

POST /users creates a new user record from the request body and returns the
created user. The endpoint sends a welcome email as a non-blocking side effect.

Accepts: id (auto-assigned), name (required, non-empty string), email
(required, valid email format).

Returns: the created user with id, name, and email. HTTP 201 on success.

Errors:
- 422 if name is empty or email is not a valid email address (Pydantic validation)
- 409 if a user with the same email already exists
```

**Generated code:**

```python
from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr


class UserResponse(BaseModel):
    id: int
    name: str
    email: str

    model_config = {"from_attributes": True}


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(
    body: CreateUserRequest,
    db: DbSession,
    tasks: BackgroundTasks,
) -> UserResponse:
    existing = await db.get_user_by_email(body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered.")
    user = await db.create_user(name=body.name, email=body.email)
    tasks.add_task(send_welcome_email, user.email)
    return UserResponse.model_validate(user)
```

Observe: `Annotated` DI, `response_model` on the decorator, separate request/response schemas, `async def` (because async SQLAlchemy is in use), background task for email.
