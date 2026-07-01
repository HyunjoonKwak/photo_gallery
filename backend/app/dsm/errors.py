"""DSM Web API error handling.

DSM returns errors as ``{"success": false, "error": {"code": <int>}}``.
We map the documented codes to friendly messages so the UI never leaks raw
codes or credentials. Unknown codes fall back to a generic message + the code.
"""


class DsmError(Exception):
    """Raised when a DSM Web API call returns success=false or transport fails."""

    def __init__(self, code: int, message: str, api: str | None = None):
        self.code = code
        self.api = api
        super().__init__(message)


# DSM error codes that mean the session id (sid) is no longer usable and the
# user must re-authenticate: 106 session timeout, 107 interrupted by a login
# elsewhere, 119 invalid sid. (105 is "insufficient permission" — a 403, not a
# re-login case — so it is deliberately excluded.)
SESSION_INVALID_CODES: frozenset[int] = frozenset({106, 107, 119})


# Generic / common API error codes (Synology File Station API Guide).
COMMON_ERRORS: dict[int, str] = {
    100: "알 수 없는 오류가 발생했습니다.",
    101: "잘못된 파라미터입니다.",
    102: "요청한 API가 존재하지 않습니다.",
    103: "요청한 메서드가 존재하지 않습니다.",
    104: "이 API 버전은 지원되지 않습니다.",
    105: "이 계정에는 작업 권한이 없습니다.",
    106: "세션이 만료되었습니다. 다시 로그인하세요.",
    107: "다른 위치에서 로그인되어 세션이 중단되었습니다.",
    119: "세션(SID)이 유효하지 않습니다. 다시 로그인하세요.",
}

# SYNO.API.Auth specific error codes.
AUTH_ERRORS: dict[int, str] = {
    400: "계정 또는 비밀번호가 올바르지 않습니다.",
    401: "계정이 비활성화되었습니다.",
    402: "권한이 거부되었습니다.",
    403: "2단계 인증(OTP) 코드가 필요합니다.",
    404: "2단계 인증(OTP) 코드가 올바르지 않습니다.",
    406: "OTP 강제 정책으로 로그인할 수 없습니다.",
    407: "허용되지 않은 IP에서의 접근입니다.",
    408: "비밀번호가 만료되어 변경이 필요합니다.",
    409: "비밀번호가 만료되었습니다.",
    410: "비밀번호를 변경해야 합니다.",
}

# SYNO.Foto.* / SYNO.FotoTeam.* specific error codes.
# Synology Photos has no official API docs; these are the codes observed in the
# community-documented API. Refine against a real NAS as the photo features land.
FOTO_ERRORS: dict[int, str] = {
    800: "사진 작업 요청이 올바르지 않습니다.",
    801: "요청한 사진 또는 앨범을 찾을 수 없습니다.",
    802: "이 사진 작업을 수행할 권한이 없습니다.",
    803: "Synology Photos가 아직 인덱싱 중입니다. 잠시 후 다시 시도하세요.",
}

# SYNO.FileStation.* specific error codes.
FILESTATION_ERRORS: dict[int, str] = {
    400: "잘못된 파일 작업 파라미터입니다.",
    401: "알 수 없는 파일 작업 오류입니다.",
    402: "시스템이 이 작업을 허용하지 않습니다.",
    403: "이 작업에는 관리자 권한이 필요합니다.",
    404: "지정한 사용자가 존재하지 않습니다.",
    405: "지정한 그룹이 존재하지 않습니다.",
    406: "해당 작업을 위한 권한이 없습니다.",
    407: "대상이 사용 중(잠김)입니다.",
    408: "경로를 찾을 수 없습니다.",
    409: "권한이 없는 작업입니다.",
    410: "디스크 용량이 부족합니다.",
    414: "이미 같은 이름의 항목이 존재합니다.",
    415: "휴지통이 비활성화되어 있습니다.",
    417: "대상 경로에 접근할 수 없습니다.",
}


def message_for(api: str, code: int) -> str:
    """Resolve a friendly Korean message for a DSM error code under an API."""
    if api.startswith("SYNO.API.Auth"):
        table = {**COMMON_ERRORS, **AUTH_ERRORS}
    elif api.startswith("SYNO.FileStation"):
        table = {**COMMON_ERRORS, **FILESTATION_ERRORS}
    elif api.startswith(("SYNO.Foto", "SYNO.FotoTeam")):
        table = {**COMMON_ERRORS, **FOTO_ERRORS}
    else:
        table = COMMON_ERRORS
    return table.get(code, f"DSM 오류가 발생했습니다 (code={code}).")
