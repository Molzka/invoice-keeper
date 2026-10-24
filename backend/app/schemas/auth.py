from pydantic import BaseModel, ConfigDict, Field

from app.schemas.users import Username, UserRead


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: Username
    password: str = Field(min_length=1, max_length=128, repr=False)


class AuthResponse(BaseModel):
    user: UserRead
    csrf_token: str
