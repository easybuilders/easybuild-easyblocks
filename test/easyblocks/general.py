##
# Copyright 2015-2026 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/easybuilders/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
"""
General unit tests for the easybuild-easyblocks repo.

@author: Kenneth Hoste (Ghent University)
"""
import itertools
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import TestLoader, TextTestRunner
from typing import List, Set

from easybuild.base.testing import TestCase
from easybuild.easyblocks import VERSION
from easybuild.framework.easyconfig.tools import get_paths_for
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import read_file, write_file
from easybuild.tools.run import run_shell_cmd


EASYBLOCK_BODY = """
from easybuild.framework.easyblock import EasyBlock
class EB_%s(EasyBlock):
    pass
"""
EASYBLOCKS_FLATTEN_EXTEND_PATH = """
subdirs = [chr(l) for l in range(ord('a'), ord('z') + 1)] + ['0']
for subdir in subdirs:
    __path__ = extend_path(__path__, '%s.%s' % (__name__, subdir))
"""
NAMESPACE_EXTEND_PATH = "from pkgutil import extend_path; __path__ = extend_path(__path__, __name__)"
EASYBLOCKS_VERSION = "VERSION = '%s'" % VERSION


def det_path_for_import(module, pythonpath=None):
    """Determine filepath obtained when importing specified module."""
    cmd_tmpl = "python -c 'import %(mod)s; print(%(mod)s.__file__)'"

    if pythonpath:
        cmd_tmpl = "PYTHONPATH=%s:$PYTHONPATH %s" % (pythonpath, cmd_tmpl)

    cmd = cmd_tmpl % {'mod': module}

    res = run_shell_cmd(cmd, hidden=True, fail_on_error=False)

    if res.exit_code:
        raise EasyBuildError(res.output)

    # only return last line that should contain path to imported module
    # warning messages may precede it
    return res.output.strip().split('\n')[-1]


def up(path, level):
    """Determine parent path for given path, N levels up."""
    while level:
        path = os.path.dirname(path)
        level -= 1
    return path


class GeneralEasyblockTest(TestCase):
    """General easybuild-easyblocks tests."""

    def setUp(self):
        """Test setup."""
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.cwd = os.getcwd()

    def tearDown(self):
        """Test cleanup."""
        super().tearDown()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir)

    def test_custom_easyblocks_repo(self):
        """Test whether using a custom easyblocks repo works as expected."""
        easyblocks_path = up(os.path.abspath(__file__), 3)

        # determine path to where easybuild.framework is imported from, so we can hard set $PYTHONPATH
        # this is required to dance around issues with easy-install.pth files determining the actual Python search path
        # see also
        # http://blog.olgabotvinnik.com/blog/2014/03/03/2014-03-03-pythonpath-is-a-liar-site-py-and-easy-install-pth-tell/
        import easybuild.framework  # pylint: disable=import-outside-toplevel
        framework_path = up(easybuild.framework.__file__, 3)

        # prepend path to easybuild-easyblocks repo to $PYTHONPATH, so we're in full(?) control
        pythonpath = os.environ.get('PYTHONPATH', '')
        os.environ['PYTHONPATH'] = os.pathsep.join([easyblocks_path, framework_path, pythonpath])

        # set up custom easyblocks repo
        custom_easyblocks_repo_path = os.path.join(self.tmpdir, 'myeasyblocks')
        os.makedirs(os.path.join(custom_easyblocks_repo_path, 'easybuild', 'easyblocks'))

        def write_module(path, txt):
            """Write provided contents to module at given path in custom easyblocks repo."""
            write_file(os.path.join(custom_easyblocks_repo_path, 'easybuild', path), txt)

        # this test should be run out of the easyblocks repository,
        # to avoid that the working directory that is prepended to the Python search path affects the test results
        os.chdir(self.tmpdir)

        eb_easyblocks = [
            ('easybuild.easyblocks', 3),  # easybuild.easyblocks.__init__.py
            ('easybuild.easyblocks.gcc', 4),  # easybuild.easyblocks.g.gcc.py
            # note: R easyblock is a special case, due to clash with 'easybuild.easyblocks.r' namespace
            ('easybuild.easyblocks.r', 4),  # easybuild.easyblocks.r.__init__.py
        ]
        for (mod, depth) in eb_easyblocks:
            res = det_path_for_import(mod)
            parent_path = up(res, depth)
            msg = "parent path for '%s' module %s == %s" % (mod, parent_path, easyblocks_path)
            self.assertTrue(os.path.samefile(easyblocks_path, parent_path), msg)

        # importing EB_R class from easybuild.easyblocks.r works fine
        run_shell_cmd("python -c 'from easybuild.easyblocks.r import EB_R'", hidden=True)

        # importing a non-existing module fails
        err_msg = "No module named .*"
        self.assertErrorRegex(EasyBuildError, err_msg, det_path_for_import, 'easybuild.easyblocks.nosuchsoftwarefoobar')

        # define easybuild.easyblocks namespace in custom easyblocks repo
        write_module('__init__.py', NAMESPACE_EXTEND_PATH)
        txt = '\n'.join([NAMESPACE_EXTEND_PATH, EASYBLOCKS_VERSION, EASYBLOCKS_FLATTEN_EXTEND_PATH])
        write_module(os.path.join('easyblocks', '__init__.py'), txt)

        # add custom easyblock for foobar
        write_module(os.path.join('easyblocks', 'foobar.py'), EASYBLOCK_BODY % 'foobar')

        # test importing from both easyblocks repos
        easyblocks = eb_easyblocks + [('easybuild.easyblocks.foobar', 3)]
        repo_paths = [
            custom_easyblocks_repo_path,  # easybuild.easyblocks is now initialised via custom easyblocks repo
            easyblocks_path,  # GCC easyblock
            easyblocks_path,  # R easyblock/package
            custom_easyblocks_repo_path,  # foobar easyblock
        ]
        for (mod, depth), repo_path in zip(easyblocks, repo_paths):
            res = det_path_for_import(mod, pythonpath=custom_easyblocks_repo_path)
            parent_path = up(res, depth)
            msg = "parent path for '%s' module %s == %s" % (mod, parent_path, repo_path)
            self.assertTrue(os.path.samefile(repo_path, parent_path), msg)

        # importing EB_R class from easybuild.easyblocks.r still works fine
        run_shell_cmd("python -c 'from easybuild.easyblocks.r import EB_R'", hidden=True)

        # custom easyblocks override existing easyblocks (with custom easyblocks repo first in $PYTHONPATH)
        for software in ['GCC', 'R']:
            write_module(os.path.join('easyblocks', '%s.py' % software.lower()), EASYBLOCK_BODY % software)
            mod = 'easybuild.easyblocks.%s' % software.lower()
            res = det_path_for_import(mod, pythonpath=custom_easyblocks_repo_path)
            parent_path = up(res, 3)
            msg = "parent path for '%s' module %s == %s" % (mod, parent_path, custom_easyblocks_repo_path)
            self.assertTrue(os.path.samefile(custom_easyblocks_repo_path, parent_path), msg)

        # importing EB_R class from easybuild.easyblocks.r still works fine
        run_shell_cmd("python -c 'from easybuild.easyblocks.r import EB_R'", hidden=True)

    def test_imports(self):
        """Check that for correct imports of other easyblocks

        All imports should be like:
        from easybuild.easyblocks import cmake
        from easybuild.easyblocks.generic import pythonpackage
        import easybuild.easyblocks.cmake
        import easybuild.easyblocks.generic.pythonpackage

        NOT using the lettered imports (breaks --include-easyblocks*): import easybuild.easyblocks.c.cmake
        """
        easyblocks_path = Path(get_paths_for("easyblocks")[0])
        easyblocks: List[Path] = [eb for eb in easyblocks_path.rglob('*.py')
                                  if eb.name != '__init__.py' and eb.parent.name != 'test']
        easyblock_names: Set[str] = {eb.stem for eb in easyblocks}
        generic_easyblocks: Set[str] = {eb.stem for eb in easyblocks if eb.parent.name == 'generic'}
        failures: List[str] = []
        for eb in easyblocks:
            # Search for all imports of easyblocks and extract the name
            contents: str = read_file(eb)
            imports = itertools.chain(
                re.finditer(r'(from easybuild\.easyblocks(\.(?P<module>[^ ]+))?) import (?P<names>.+)', contents),
                re.finditer(r'import (easybuild\.easyblocks\.(?P<module>[^ ]+))', contents),
            )
            for imp in imports:
                module = (imp['module'] or '').split('.')
                if module and module[-1] in easyblock_names:
                    imported_eb = module[-1]
                    if imported_eb in generic_easyblocks:
                        if module[:-1] != ['generic']:
                            failures.append(f"Wrong import of generic easyblock '{imported_eb}' in {eb.name}: {imp[1]}")
                    elif len(module) != 1:  # Should import directly, i.e. not 'easybuild.easyblocks.p.python'
                        failures.append(f"Wrong import of custom easyblock '{imported_eb}' in {eb.name}: {imp[1]}")
                else:
                    try:
                        names = imp['names']
                    except IndexError:
                        continue
                    for imported_eb in re.split(', *', names or ''):
                        imported_eb = re.sub(r' as .+', '', imported_eb)
                        if imported_eb not in easyblock_names:
                            continue
                        if imported_eb in generic_easyblocks:
                            if module != ['generic']:
                                failures.append(f"Wrong import of generic easyblock '{imported_eb}' in {eb.name}: "
                                                f"{imp[1]}")
                        elif module:  # Should import directly, i.e. not 'from easybuild.easyblocks.p import python'
                            failures.append(f"Wrong import of custom easyblock '{imported_eb}' in {eb.name}: {imp[1]}")
        if failures:
            self.fail('\n'.join(failures))


def suite(loader):
    """Return all general easybuild-easyblocks tests."""
    return loader.loadTestsFromTestCase(GeneralEasyblockTest)


if __name__ == '__main__':
    res = TextTestRunner(verbosity=1).run(suite(TestLoader()))
    sys.exit(len(res.failures))
