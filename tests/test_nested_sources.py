import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kindlecomicconverter import comic2ebook


class NestedSourceTests(unittest.TestCase):
    def setUp(self):
        comic2ebook.options = SimpleNamespace(
            cropping=0,
            profileData=(None, (1264, 1680)),
        )

    def test_recursively_expands_nested_archives(self):
        with tempfile.TemporaryDirectory() as workspace:
            outer = os.path.join(workspace, 'outer.cbz')
            with open(outer, 'wb'):
                pass

            def extract(archive, target):
                if archive.filepath.endswith('outer.cbz'):
                    with open(os.path.join(target, 'inner.cbz'), 'wb'):
                        pass
                else:
                    with open(os.path.join(target, 'page.jpg'), 'wb') as image:
                        image.write(b'image')
                return target

            with patch.object(
                comic2ebook.comicarchive.ComicArchive,
                'extract',
                autospec=True,
                side_effect=extract,
            ) as mocked_extract:
                comic2ebook.expandNestedSources(workspace)

            self.assertEqual(mocked_extract.call_count, 2)
            self.assertFalse(os.path.exists(outer))
            pages = [
                os.path.join(root, name)
                for root, _, files in os.walk(workspace)
                for name in files
                if name == 'page.jpg'
            ]
            self.assertEqual(len(pages), 1)

    def test_rejects_sources_beyond_depth_limit(self):
        with tempfile.TemporaryDirectory() as workspace:
            nested = os.path.join(workspace, 'too-deep.cbz')
            with open(nested, 'wb'):
                pass

            with self.assertRaisesRegex(RuntimeError, 'depth exceeds'):
                comic2ebook.expandNestedSources(
                    workspace,
                    depth=comic2ebook.MAX_NESTED_SOURCE_DEPTH,
                )


if __name__ == '__main__':
    unittest.main()
