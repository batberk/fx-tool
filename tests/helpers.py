def assert_error(response, status, code):
    assert response.status_code == status
    assert response.json().keys() == {"error", "message"}
    assert response.json()["error"] == code
