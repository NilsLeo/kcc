import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace

from kindlecomicconverter import comic2ebook


CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

# A one-pixel JPEG is enough: getWorkFolder only stats and copies these files.
JPEG_BYTES = bytes.fromhex(
    'ffd8ffe000104a46494600010100000100010000ffdb004300ff'
    'ffffffffffffffffffffffffffffffffffffffffffffffffffff'
    'ffffffffffffffffffffffffffffffffffffffffffffffffffff'
    'ffffffffffffffffffffffffffffffffffffffffffffffffffff'
    'ffffffffffffffffffc00011080001000103012200021101031101'
    'ffc4001f0000010501010101010100000000000000000102030405'
    '060708090a0bffc400b5100002010303020403050504040000017d'
    '01020300041105122131410613516107227114328191a1082342b1'
    'c11552d1f02433627282090a161718191a25262728292a34353637'
    '38393a434445464748494a535455565758595a636465666768696a'
    '737475767778797a838485868788898a92939495969798999aa2a3'
    'a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3'
    'd4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa'
    'ffda0008010100003f00fbfeffd9'
)


def _build_epub(path, image_names, spine_pages, page_bodies):
    """Write a minimal EPUB with a flat archive root (no OEBPS/ directory)."""
    manifest = ['<item id="page%d" href="%s" media-type="application/xhtml+xml"/>' % (i, name)
                for i, name in enumerate(spine_pages)]
    manifest += ['<item id="img%d" href="%s" media-type="image/jpeg"/>' % (i, name)
                 for i, name in enumerate(image_names)]
    itemrefs = ['<itemref idref="page%d"/>' % i for i in range(len(spine_pages))]
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="uid">\n'
        '<metadata/>\n<manifest>\n%s\n</manifest>\n<spine>\n%s\n</spine>\n</package>\n'
        % ('\n'.join(manifest), '\n'.join(itemrefs))
    )
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('mimetype', 'application/epub+zip')
        archive.writestr('META-INF/container.xml', CONTAINER_XML)
        archive.writestr('content.opf', opf)
        for name, body in zip(spine_pages, page_bodies):
            archive.writestr(name, body)
        for name in image_names:
            archive.writestr(name, JPEG_BYTES)


def _page(*image_names):
    imgs = ''.join('<img src="%s"/>' % name for name in image_names)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body>%s</body></html>\n' % imgs)


def _extracted_images(workdir):
    images_dir = os.path.join(workdir, 'OEBPS', 'Images')
    if not os.path.isdir(images_dir):
        return []
    return sorted(os.listdir(images_dir), key=lambda name: int(os.path.splitext(name)[0]))


class EpubSpineManifestMismatchTests(unittest.TestCase):
    def setUp(self):
        comic2ebook.options = SimpleNamespace(
            lightnovel=False,
            legacyextract=False,
            tempdir=None,
        )

    def test_falls_back_to_manifest_when_spine_misses_most_images(self):
        """Manifest declares 20 images but a single spine page shows them all."""
        with tempfile.TemporaryDirectory() as workspace:
            images = ['index-%d_1.jpg' % i for i in range(1, 21)]
            epub = os.path.join(workspace, 'flat.epub')
            _build_epub(epub, images, ['index.html'], [_page(*images)])

            workdir = comic2ebook.getWorkFolder(epub)
            try:
                extracted = _extracted_images(workdir)
                # Without the fallback the spine yields a single image.
                self.assertEqual(len(extracted), len(images))
            finally:
                comic2ebook.rmtree(workdir, True)

    def test_manifest_fallback_preserves_manifest_order(self):
        with tempfile.TemporaryDirectory() as workspace:
            images = ['index-%d_1.jpg' % i for i in range(1, 21)]
            epub = os.path.join(workspace, 'flat.epub')
            _build_epub(epub, images, ['index.html'], [_page(*images)])

            workdir = comic2ebook.getWorkFolder(epub)
            try:
                extracted = _extracted_images(workdir)
                # Copies are renamed to their ordinal, so order is positional.
                self.assertEqual(extracted[0], '0.jpg')
                self.assertEqual(extracted[-1], '19.jpg')
            finally:
                comic2ebook.rmtree(workdir, True)

    def test_well_formed_spine_is_left_untouched(self):
        """Regression guard: one image per spine page must keep spine ordering."""
        with tempfile.TemporaryDirectory() as workspace:
            images = ['index-%d_1.jpg' % i for i in range(1, 11)]
            pages = ['page-%d.xhtml' % i for i in range(1, 11)]
            bodies = [_page(name) for name in images]
            epub = os.path.join(workspace, 'wellformed.epub')
            _build_epub(epub, images, pages, bodies)

            workdir = comic2ebook.getWorkFolder(epub)
            try:
                self.assertEqual(len(_extracted_images(workdir)), len(images))
            finally:
                comic2ebook.rmtree(workdir, True)

    def test_no_fallback_when_spine_covers_enough_images(self):
        """A cover-only shortfall stays above the threshold and must not trigger."""
        with tempfile.TemporaryDirectory() as workspace:
            images = ['cover.jpg'] + ['index-%d_1.jpg' % i for i in range(1, 11)]
            pages = ['page-%d.xhtml' % i for i in range(1, 11)]
            bodies = [_page('index-%d_1.jpg' % i) for i in range(1, 11)]
            epub = os.path.join(workspace, 'cover.epub')
            _build_epub(epub, images, pages, bodies)

            workdir = comic2ebook.getWorkFolder(epub)
            try:
                # 10 of 11 images: above the 50% threshold, so the unreferenced
                # cover must not drag the book into the manifest path.
                self.assertEqual(len(_extracted_images(workdir)), 10)
            finally:
                comic2ebook.rmtree(workdir, True)


if __name__ == '__main__':
    unittest.main()
