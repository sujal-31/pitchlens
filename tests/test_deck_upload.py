"""Unit tests for the PDF deck upload endpoint (POST /api/decks)."""

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from PyPDF2 import PdfWriter

from app.main import app


def create_valid_pdf(num_pages: int = 3) -> bytes:
    """Create a minimal valid PDF with the given number of pages."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def create_mock_user():
    """Create a mock authenticated user."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    return user


@pytest.fixture
def mock_user():
    return create_mock_user()


@pytest.fixture
def mock_db():
    """Create a mock async database session that supports add and flush."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def authenticated_client(mock_user, mock_db):
    """Override dependencies to simulate an authenticated user with a mock DB."""
    from app.api.dependencies import get_current_user
    from app.db.database import get_db

    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_db] = lambda: mock_db
    yield
    app.dependency_overrides.clear()


class TestDeckUploadSuccess:
    """Tests for successful deck upload."""

    @pytest.mark.asyncio
    async def test_successful_upload_valid_pdf(self, authenticated_client, mock_user):
        """A valid PDF under size and page limits returns 202 with deck_id and analysis_id."""
        pdf_content = create_valid_pdf(num_pages=5)

        with patch("app.api.decks.UPLOAD_DIR") as mock_dir, \
             patch("app.api.decks.run_pipeline", new_callable=AsyncMock) as mock_pipeline:
            mock_path = MagicMock()
            mock_dir.__truediv__ = MagicMock(return_value=mock_path)
            mock_dir.mkdir = MagicMock()
            mock_path.write_bytes = MagicMock()
            mock_path.exists = MagicMock(return_value=False)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/decks/",
                    files={"file": ("test_deck.pdf", pdf_content, "application/pdf")},
                )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert "deck_id" in data
        assert "analysis_id" in data
        assert data["file_name"] == "test_deck.pdf"
        assert data["page_count"] == 5


class TestDeckUploadValidation:
    """Tests for upload validation errors."""

    @pytest.mark.asyncio
    async def test_reject_non_pdf_file(self, authenticated_client):
        """A non-PDF file is rejected with 400 and invalid format message."""
        non_pdf_content = b"This is not a PDF file content"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/decks/",
                files={"file": ("document.txt", non_pdf_content, "text/plain")},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid file format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_reject_oversized_file(self, authenticated_client):
        """A file exceeding 20 MB is rejected with 400 and size limit message."""
        # Create content just over 20 MB (we simulate by patching the read)
        oversized_content = b"x" * (20 * 1024 * 1024 + 1)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/decks/",
                files={"file": ("big.pdf", oversized_content, "application/pdf")},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "File size limit exceeded" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_reject_pdf_over_50_pages(self, authenticated_client):
        """A PDF with more than 50 pages is rejected with 400 and page limit message."""
        pdf_content = create_valid_pdf(num_pages=51)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/decks/",
                files={"file": ("many_pages.pdf", pdf_content, "application/pdf")},
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Page limit exceeded" in response.json()["detail"]


class TestDeckUploadAuthentication:
    """Tests for authentication requirements."""

    @pytest.mark.asyncio
    async def test_reject_unauthenticated_request(self):
        """A request without valid auth credentials is rejected with 401."""
        # Clear any dependency overrides to test real auth
        app.dependency_overrides.clear()

        pdf_content = create_valid_pdf(num_pages=2)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/decks/",
                files={"file": ("deck.pdf", pdf_content, "application/pdf")},
            )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDeckUploadStorageFailure:
    """Tests for storage failure handling."""

    @pytest.mark.asyncio
    async def test_storage_failure_returns_500(self, authenticated_client):
        """If file storage fails, a 500 error is returned without a deck_id."""
        pdf_content = create_valid_pdf(num_pages=3)

        with patch("app.api.decks.UPLOAD_DIR") as mock_dir:
            mock_dir.mkdir = MagicMock(side_effect=OSError("Disk full"))

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/decks/",
                    files={"file": ("deck.pdf", pdf_content, "application/pdf")},
                )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Storage failure" in response.json()["detail"]
        assert "deck_id" not in response.json()
