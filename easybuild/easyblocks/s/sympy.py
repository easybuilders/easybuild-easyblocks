# Author: Caspar van Leeuwen (SURF)

import os
import tempfile

from easybuild.easyblocks.generic.pythonpackage import PythonPackage


class EB_sympy(PythonPackage):
    """Build sympy"""

    def test_step(self):
        original_tmpdir = tempfile.gettempdir()
        print("Old TMPDIR: %s" % original_tmpdir)
        tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
        self.log.debug("Changing TMPDIR for test step to avoid easybuild-easyconfigs issue #17593.")
        self.log.debug("Old TMPDIR %s. New TMPDIR %s.", original_tmpdir, tempfile.gettempdir())
        super(EB_sympy, self).test_step(self)
        tempfile.tempdir = original_tmpdir
        self.log.debug("Restored TMPDIR to %s", tempfile.gettempdir())
