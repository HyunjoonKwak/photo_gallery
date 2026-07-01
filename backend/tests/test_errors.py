"""Unit tests for the DSM error-code → Korean message mapping."""

from app.dsm.errors import SESSION_INVALID_CODES, message_for


def test_auth_specific_code():
    assert message_for("SYNO.API.Auth", 400) == "계정 또는 비밀번호가 올바르지 않습니다."


def test_auth_otp_code():
    assert message_for("SYNO.API.Auth", 403) == "2단계 인증(OTP) 코드가 필요합니다."


def test_filestation_specific_code():
    assert message_for("SYNO.FileStation.List", 408) == "경로를 찾을 수 없습니다."


def test_foto_routes_to_foto_table():
    assert message_for("SYNO.Foto.Browse.Item", 803).startswith("Synology Photos")


def test_fototeam_shares_foto_table():
    assert message_for("SYNO.FotoTeam.Browse.Folder", 801) == message_for(
        "SYNO.Foto.Browse.Folder", 801
    )


def test_common_code_available_under_every_api():
    # 106 (session timeout) is a common code, resolvable regardless of API family.
    for api in ("SYNO.API.Auth", "SYNO.FileStation.List", "SYNO.Foto.Browse.Item"):
        assert "세션" in message_for(api, 106)


def test_unknown_code_falls_back_with_code_number():
    msg = message_for("SYNO.FileStation.List", 9999)
    assert "9999" in msg


def test_session_invalid_codes_are_the_reauth_set():
    assert SESSION_INVALID_CODES == frozenset({106, 107, 119})
