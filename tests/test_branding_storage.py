import io
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import branding_storage


class BrandingStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.original_paths = {
            name: getattr(branding_storage, name)
            for name in (
                "STATIC_ROOT",
                "BRANDING_ROOT",
                "TIS_LOGO_ROOT",
                "ORGANIZATIONS_ROOT",
            )
        }
        branding_storage.STATIC_ROOT = self.root / "static"
        branding_storage.BRANDING_ROOT = branding_storage.STATIC_ROOT / "branding"
        branding_storage.TIS_LOGO_ROOT = (
            branding_storage.BRANDING_ROOT / "tis" / "logos"
        )
        branding_storage.ORGANIZATIONS_ROOT = (
            branding_storage.BRANDING_ROOT / "organizations"
        )
    def tearDown(self):
        for name, value in self.original_paths.items():
            setattr(branding_storage, name, value)
        self.temp_dir.cleanup()

    @staticmethod
    def _png_bytes(width=600, height=200):
        output = io.BytesIO()
        Image.new("RGBA", (width, height), (10, 78, 163, 255)).save(
            output,
            format="PNG",
        )
        return output.getvalue()

    def test_organization_and_branch_logo_directories_are_tenant_scoped(self):
        organization_dir = branding_storage.ensure_organization_logo_dir(7)
        branch_dir = branding_storage.ensure_branch_logo_dir(7, 12)

        self.assertEqual(
            organization_dir,
            self.root / "static" / "branding" / "organizations" / "7" / "logos",
        )
        self.assertEqual(
            branch_dir,
            self.root
            / "static"
            / "branding"
            / "organizations"
            / "7"
            / "branches"
            / "12"
            / "logos",
        )
        self.assertTrue(organization_dir.is_dir())
        self.assertTrue(branch_dir.is_dir())

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(branding_storage.BrandingStorageError):
            branding_storage.resolve_organization_asset_path(
                1,
                "logos/../../2/logos/private.png",
                require_file=False,
            )
        with self.assertRaises(branding_storage.BrandingStorageError):
            branding_storage.resolve_organization_asset_path(
                1,
                "/logos/private.png",
                require_file=False,
            )

    def test_logo_path_cannot_be_resolved_for_another_tenant(self):
        relative_path = branding_storage.write_logo_file(
            self._png_bytes(),
            school_group_id=1,
            slot_key="primary",
            extension=".png",
        )
        with self.assertRaises(branding_storage.BrandingStorageError):
            branding_storage.resolve_owned_logo_path(
                relative_path,
                school_group_id=2,
            )

    def test_cross_tenant_access_is_denied(self):
        self.assertTrue(
            branding_storage.can_access_organization_assets(1, 1)
        )
        self.assertFalse(
            branding_storage.can_access_organization_assets(1, 2)
        )
        self.assertTrue(
            branding_storage.can_access_organization_assets(
                1,
                2,
                can_manage_all=True,
            )
        )

    def test_platform_variant_selection_matches_background_and_layout(self):
        self.assertIn(
            "Full Color",
            branding_storage.tis_logo_relative_path(
                theme="light",
                layout="horizontal",
            ),
        )
        self.assertIn(
            "White & Light Orange",
            branding_storage.tis_logo_relative_path(
                theme="dark",
                layout="stacked",
            ),
        )
        self.assertIn(
            "Wordmark Only",
            branding_storage.tis_logo_relative_path(
                theme="dark",
                compact=True,
            ),
        )

    def test_legacy_migration_copies_and_keeps_original(self):
        source_dir = (
            branding_storage.STATIC_ROOT
            / "uploads"
            / "school_group_logos"
            / "1"
        )
        source_dir.mkdir(parents=True)
        source = source_dir / "primary_legacy.png"
        source.write_bytes(self._png_bytes())

        migrated_path = branding_storage.migrate_legacy_logo_file(
            "uploads/school_group_logos/1/primary_legacy.png",
            school_group_id=1,
        )

        self.assertEqual(
            migrated_path,
            "branding/organizations/1/logos/primary_legacy.png",
        )
        self.assertTrue(source.is_file())
        self.assertTrue(
            (
                branding_storage.STATIC_ROOT
                / "branding"
                / "organizations"
                / "1"
                / "logos"
                / "primary_legacy.png"
            ).is_file()
        )

    def test_public_static_mount_blocks_tenant_logos_only(self):
        tis_file = (
            branding_storage.STATIC_ROOT
            / "branding"
            / "tis"
            / "logos"
            / "platform.png"
        )
        tenant_file = (
            branding_storage.STATIC_ROOT
            / "branding"
            / "organizations"
            / "1"
            / "logos"
            / "primary.png"
        )
        tis_file.parent.mkdir(parents=True)
        tenant_file.parent.mkdir(parents=True)
        tis_file.write_bytes(self._png_bytes())
        tenant_file.write_bytes(self._png_bytes())
        legacy_file = (
            branding_storage.STATIC_ROOT
            / "uploads"
            / "school_group_logos"
            / "1"
            / "legacy.png"
        )
        legacy_file.parent.mkdir(parents=True)
        legacy_file.write_bytes(self._png_bytes())

        app = FastAPI()
        app.mount(
            "/static",
            branding_storage.ProtectedBrandingStaticFiles(
                directory=branding_storage.STATIC_ROOT
            ),
        )
        client = TestClient(app)

        self.assertEqual(
            client.get("/static/branding/tis/logos/platform.png").status_code,
            200,
        )
        self.assertEqual(
            client.get(
                "/static/branding/organizations/1/logos/primary.png"
            ).status_code,
            404,
        )
        self.assertEqual(
            client.get(
                "/static/uploads/school_group_logos/1/legacy.png"
            ).status_code,
            404,
        )

    def test_upload_validation_checks_dimensions_and_svg_safety(self):
        valid = branding_storage.validate_logo_upload(
            self._png_bytes(),
            "main.png",
            slot_key="primary",
        )
        self.assertEqual(valid.extension, ".png")
        self.assertEqual((valid.width, valid.height), (600, 200))

        with self.assertRaises(branding_storage.BrandingStorageError):
            branding_storage.validate_logo_upload(
                self._png_bytes(64, 64),
                "favicon.png",
                slot_key="favicon",
            )

        unsafe_svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 200">'
            b'<script>alert(1)</script></svg>'
        )
        with self.assertRaises(branding_storage.BrandingStorageError):
            branding_storage.validate_logo_upload(
                unsafe_svg,
                "unsafe.svg",
                slot_key="primary",
            )


if __name__ == "__main__":
    unittest.main()
