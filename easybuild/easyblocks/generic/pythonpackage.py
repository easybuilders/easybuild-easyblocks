##
# Copyright 2009-2013 Ghent University
#
# This file is part of EasyBuild,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://vscentrum.be/nl/en),
# the Hercules foundation (http://www.herculesstichting.be/in_English)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# http://github.com/hpcugent/easybuild
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
EasyBuild support for Python packages, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
import os
import re
import shutil
import tempfile
from os.path import expanduser
from vsc import fancylogger

import easybuild.tools.environment as env
from easybuild.easyblocks.python import EXTS_FILTER_PYTHON_PACKAGES
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.filetools import mkdir, rmtree2, run_cmd, write_file
from easybuild.tools.modules import get_software_version


# test setup.py script for PythonPackage.python_safe_install
TEST_SETUP_PY = """#!/usr/bin/env python
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='%(pkg)s',
    version='1.0',
    scripts=['%(pkg)s.py'],
    packages=['%(pkg)s'],
    data_files=['%(pkg)s.txt'],
    provides=['%(pkg)s.py', '%(pkg)s'],
    zip_safe=False,
)
"""
TEST_SCRIPT_PY = """#!/usr/bin/env python
import os, sys
sys.stdout.write(os.path.dirname(os.path.abspath(__file__)))
"""
TEST_INIT_PY = """import os, sys
def where():
   sys.stdout.write(os.path.dirname(os.path.abspath(__file__)))
"""


def det_pylibdir():
    """Determine Python library directory."""
    log = fancylogger.getLogger('det_pylibdir', fname=False)
    pyver = get_software_version('Python')
    if not pyver:
        log.error("Python module not loaded.")
    else:
        # determine Python lib dir via distutils
        # use run_cmd, we can to talk to the active Python, not the system Python running EasyBuild
        prefix = '/tmp/'
        pycmd = 'import distutils.sysconfig; print(distutils.sysconfig.get_python_lib(prefix="%s"))' % prefix
        cmd = "python -c '%s'" % pycmd
        out, ec = run_cmd(cmd, simple=False)
        out = out.strip()

        # value obtained should start with specified prefix, otherwise something is very wrong
        if not out.startswith(prefix):
            tup = (cmd, prefix, out, ec)
            log.error("Output of %s does not start with specified prefix %s: %s (exit code %s)" % tup)

        pylibdir = out.strip()[len(prefix):]
        log.debug("Determined pylibdir using '%s': %s" % (cmd, pylibdir))
        return pylibdir


class PythonPackage(ExtensionEasyBlock):
    """Builds and installs a Python package, and provides a dedicated module file."""

    @staticmethod
    def extra_options():
        """Easyconfig parameters specific to Python packages."""
        extra_vars = {
            'runtest': [True, "Run unit tests.", CUSTOM],  # overrides default
        }
        return ExtensionEasyBlock.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables."""
        super(PythonPackage, self).__init__(*args, **kwargs)

        self.sitecfg = None
        self.sitecfgfn = 'site.cfg'
        self.sitecfglibdir = None
        self.sitecfgincdir = None
        self.testinstall = False
        self.testcmd = None
        self.unpack_options = ''

        self.pylibdir = None

        # make sure there's no site.cfg in $HOME, because setup.py will find it and use it
        if os.path.exists(os.path.join(expanduser('~'), 'site.cfg')):
            self.log.error('Found site.cfg in your home directory (%s), please remove it.' % expanduser('~'))

        if not 'modulename' in self.options:
            self.options['modulename'] = self.name.lower()

    def prepare_step(self):
        """Prepare easyblock by determining Python site lib dir."""
        super(PythonPackage, self).prepare_step()
        if not self.pylibdir:
            self.pylibdir = det_pylibdir()

    def prerun(self):
        """Prepare extension by determining Python site lib dir."""
        super(PythonPackage, self).prerun()
        self.pylibdir = det_pylibdir()

    def configure_step(self):
        """Configure Python package build."""

        if not self.pylibdir:
            self.log.error('Python module not loaded.')
        self.log.debug("Python library dir: %s" % self.pylibdir)

        if self.sitecfg is not None:
            # used by some extensions, like numpy, to find certain libs

            finaltxt = self.sitecfg
            if self.sitecfglibdir:
                repl = self.sitecfglibdir
                finaltxt = finaltxt.replace('SITECFGLIBDIR', repl)

            if self.sitecfgincdir:
                repl = self.sitecfgincdir
                finaltxt = finaltxt.replace('SITECFGINCDIR', repl)

            self.log.debug("Using %s: %s" % (self.sitecfgfn, finaltxt))
            try:
                if os.path.exists(self.sitecfgfn):
                    txt = open(self.sitecfgfn).read()
                    self.log.debug("Found %s: %s" % (self.sitecfgfn, txt))
                config = open(self.sitecfgfn, 'w')
                config.write(finaltxt)
                config.close()
            except IOError:
                self.log.exception("Creating %s failed" % self.sitecfgfn)

        # creates log entries for python being used, for debugging
        run_cmd("python -V")
        run_cmd("which python")
        run_cmd("python -c 'import sys; print(sys.executable)'")

    def build_step(self):
        """Build Python package using setup.py"""

        cmd = "python setup.py build %s" % self.cfg['buildopts']
        run_cmd(cmd, log_all=True, simple=True)

    def python_install(self, prefix=None, preinstallopts=None, installopts=None):
        """Install using 'python setup.py install --prefix'."""
        if prefix is None:
            prefix = self.installdir
        if preinstallopts is None:
            preinstallopts = self.cfg['preinstallopts']
        if installopts is None:
            installopts = self.cfg['installopts']

        if not self.pylibdir:
            self.pylibdir = det_pylibdir()

        # create expected directories
        abs_pylibdir = os.path.join(prefix, self.pylibdir)
        mkdir(abs_pylibdir, parents=True)

        # set PYTHONPATH as expected
        pythonpath = os.getenv('PYTHONPATH')
        env.setvar('PYTHONPATH', ":".join([x for x in [abs_pylibdir, pythonpath] if x is not None]))

        # install using setup.py
        install_cmd_template = "%(preinstallopts)s python setup.py install --prefix=%(prefix)s %(installopts)s"
        cmd = install_cmd_template % {
            'preinstallopts': preinstallopts,
            'prefix': prefix,
            'installopts': installopts,
        }
        run_cmd(cmd, log_all=True, simple=True)

        # setuptools stubbornly replaces the shebang line in scripts with
        # the full path to the Python interpreter used to install;
        # we change it (back) to '#!/usr/bin/env python' here
        shebang_re = re.compile("^#!/.*python")
        bindir = os.path.join(prefix, 'bin')
        if os.path.exists(bindir):
            for script in os.listdir(bindir):
                script = os.path.join(bindir, script)
                if os.path.isfile(script):
                    try:
                        txt = open(script, 'r').read()
                        if shebang_re.search(txt):
                            new_shebang = "#!/usr/bin/env python"
                            self.log.debug("Patching shebang header line in %s to '%s'" % (script, new_shebang))
                            txt = shebang_re.sub(new_shebang, txt)
                            open(script, 'w').write(txt)
                    except IOError, err:
                        self.log.error("Failed to patch shebang header line in %s: %s" % (script, err))

        # restore PYTHONPATH if it was set
        if pythonpath is not None:
            env.setvar('PYTHONPATH', pythonpath)

    def python_safe_install(self, **kwargs):
        """Install using 'python setup.py install --prefix', after verifying it does the right thing."""
        cwd = os.getcwd()

        # create dummy Python package to verify whether 'python setup.py install --prefix' does the right thing
        tmpdir = tempfile.mkdtemp()
        pkg = 'easybuild_pyinstalltest'
        mkdir(os.path.join(tmpdir, pkg))
        write_file(os.path.join(tmpdir, 'setup.py'), TEST_SETUP_PY % {'pkg': pkg})
        test_py_script = '%s.py' % pkg
        write_file(os.path.join(tmpdir, test_py_script), TEST_SCRIPT_PY)
        test_data_file = '%s.txt' % pkg
        write_file(os.path.join(tmpdir, test_data_file), 'data')
        write_file(os.path.join(tmpdir, pkg, '__init__.py'), TEST_INIT_PY)

        # install dummy Python package
        try:
            os.chdir(tmpdir)
            testinstalldir = tempfile.mkdtemp()
            self.python_install(prefix=testinstalldir)
            os.chdir(cwd)
        except OSError, err:
            self.log.error("Failed to move to %s: %s" % (tmpdir, err))

        # verify installation of dummy Python package
        verified = True
        full_pylibdir = os.path.join(testinstalldir, self.pylibdir)
        cmds = [
            ("python -c 'from %s import where; where()'" % pkg, full_pylibdir),
            (test_py_script, testinstalldir),
        ]
        for cmd, out_prefix in cmds:
            precmd = "PYTHONPATH=%s:$PYTHONPATH PATH=%s:$PATH" % (full_pylibdir, os.path.join(testinstalldir, 'bin'))
            fullcmd = ' '.join([precmd, cmd])
            (out, ec) = run_cmd(fullcmd, simple=False)
            tup = (out_prefix, fullcmd)
            if out.startswith(out_prefix):
                self.log.debug("Found %s in output of '%s' during verification of dummy Python installation" % tup)
            else:
                tup = (tup[0], tup[1], ec, out)
                self.log.warning("%s not found in output of '%s' (exit code: %s, output: %s)" % tup)
                verified = False
        pyver = get_software_version('Python')
        if not pyver:
            self.log.error("Python module not loaded.")
        pyver = '.'.join(pyver.split('.')[:2])
        datainstalldir = os.path.join(full_pylibdir, '%s-1.0-py%s.egg' % (pkg, pyver))
        tup = (test_data_file, datainstalldir)
        if os.path.exists(os.path.join(datainstalldir, test_data_file)):
            self.log.debug("Found file %s in %s during verification of dummy Python installation" % tup)
        else:
            self.log.warning("Failed to find file %s in %s during verification of dummy Python installation" % tup)
            verified = False

        if verified:
            self.log.debug("Verification of dummy Python installation OK.")
        else:
            self.log.error("Verification of dummy Python installation failed, setuptools not honoring --prefix?")

        # cleanup
        shutil.rmtree(testinstalldir)
        shutil.rmtree(tmpdir)

        # actually run install command
        self.python_install(**kwargs)

    def test_step(self):
        """Test the built Python package."""

        if isinstance(self.cfg['runtest'], basestring):
            self.testcmd = self.cfg['runtest']

        if self.cfg['runtest'] and not self.testcmd is None:
            extrapath = ''
            testinstalldir = None

            if self.testinstall:
                # install in test directory and export PYTHONPATH for running tests
                try:
                    testinstalldir = tempfile.mkdtemp()
                except OSError, err:
                    self.log.error("Failed to create test install dir: %s" % err)

                self.python_safe_install(prefix=testinstalldir)

                run_cmd("python -c 'import sys; print(sys.path)'")  # print Python search path (debug)
                extrapath = "export PYTHONPATH=%s:$PYTHONPATH && " % os.path.join(testinstalldir, self.pylibdir)

            if self.testcmd:
                cmd = "%s%s" % (extrapath, self.testcmd)
                run_cmd(cmd, log_all=True, simple=True)

            if testinstalldir:
                try:
                    rmtree2(testinstalldir)
                except OSError, err:
                    self.log.exception("Removing testinstalldir %s failed: %s" % (testinstalldir, err))

    def install_step(self):
        """Install Python package to a custom path using setup.py"""
        self.python_safe_install()

    def run(self):
        """Perform the actual Python package build/installation procedure"""

        if not self.src:
            self.log.error("No source found for Python package %s, required for installation. (src: %s)" % (self.name,
                                                                                                            self.src))
        super(PythonPackage, self).run(unpack_src=True)

        # configure, build, test, install
        self.configure_step()
        self.build_step()
        self.test_step()
        self.install_step()

    def sanity_check_step(self, *args, **kwargs):
        """
        Custom sanity check for Python packages
        """
        if not 'exts_filter' in kwargs:
            kwargs.update({'exts_filter': EXTS_FILTER_PYTHON_PACKAGES})
        return super(PythonPackage, self).sanity_check_step(*args, **kwargs)

    def make_module_extra(self):
        """Add install path to PYTHONPATH"""
        txt = self.moduleGenerator.prepend_paths("PYTHONPATH", [self.pylibdir])
        return super(PythonPackage, self).make_module_extra(txt)
