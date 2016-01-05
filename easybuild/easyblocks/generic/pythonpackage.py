##
# Copyright 2009-2015 Ghent University
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
import tempfile
from os.path import expanduser
from vsc.utils import fancylogger
from vsc.utils.missing import nub

import easybuild.tools.environment as env
from easybuild.easyblocks.python import EXTS_FILTER_PYTHON_PACKAGES
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import mkdir, rmtree2, which
from easybuild.tools.run import run_cmd


# not 'easy_install' deliberately, to avoid that pkg installations listed in easy-install.pth get preference
EASY_INSTALL_CMD = "python setup.py easy_install"
UNKNOWN = 'UNKNOWN'


def det_pylibdir(plat_specific=False):
    """Determine Python library directory."""
    log = fancylogger.getLogger('det_pylibdir', fname=False)

    # determine Python lib dir via distutils
    # use run_cmd, we can to talk to the active Python, not the system Python running EasyBuild
    prefix = '/tmp/'
    args = 'plat_specific=%s, prefix="%s"' % (plat_specific, prefix)
    pycmd = "import distutils.sysconfig; print(distutils.sysconfig.get_python_lib(%s))" % args
    cmd = "python -c '%s'" % pycmd

    log.debug("Determining Python library directory using %s and command '%s'", which('python'), cmd)

    out, ec = run_cmd(cmd, simple=False)
    txt = out.strip().split('\n')[-1]

    # value obtained should start with specified prefix, otherwise something is very wrong
    if not txt.startswith(prefix):
        raise EasyBuildError("Last line of output of %s does not start with specified prefix %s: %s (exit code %s)",
                             cmd, prefix, out, ec)

    pylibdir = txt[len(prefix):]
    log.debug("Determined pylibdir using '%s': %s", cmd, pylibdir)
    return pylibdir


class PythonPackage(ExtensionEasyBlock):
    """Builds and installs a Python package, and provides a dedicated module file."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to Python packages."""
        if extra_vars is None:
            extra_vars = {}
        extra_vars.update({
            'runtest': [True, "Run unit tests.", CUSTOM],  # overrides default
            'use_easy_install': [False, "Install using '%s'" % EASY_INSTALL_CMD, CUSTOM],
            'zipped_egg': [False, "Install as a zipped eggs (requires use_easy_install)", CUSTOM],
        })
        return ExtensionEasyBlock.extra_options(extra_vars=extra_vars)

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

        self.pylibdir = UNKNOWN
        self.all_pylibdirs = UNKNOWN

        # make sure there's no site.cfg in $HOME, because setup.py will find it and use it
        if os.path.exists(os.path.join(expanduser('~'), 'site.cfg')):
            raise EasyBuildError("Found site.cfg in your home directory (%s), please remove it.", expanduser('~'))

        if not 'modulename' in self.options:
            self.options['modulename'] = self.name.lower()

        if self.cfg.get('zipped_egg', False) and not self.cfg.get('use_easy_install', False):
            raise EasyBuildError("Installing zipped eggs requires use_easy_install = True")

        if self.cfg.get('use_easy_install', False):

            self.install_cmd = "%s --no-deps" % EASY_INSTALL_CMD
            if self.cfg.get('zipped_egg', False):
                self.install_cmd += " --zip-ok"
            # '.' is required at the end when using easy_install in unpacked source dir
            self.install_cmd_extra = '.'

        else:
            self.install_cmd = "python setup.py install"
            self.install_cmd_extra = None

    def set_pylibdirs(self):
        """Set Python lib directory-related class variables."""
        if self.dry_run:
            self.pylibdir = 'lib/python/site-packages'
            self.all_pylibdirs = ['lib/python/site-packages']
            self.log.debug("Using fake set of Python lib dirs during dry run: %s", self.all_pylibdirs)

        else:
            # pylibdir is the 'main' Python lib directory
            if self.pylibdir == UNKNOWN:
                self.pylibdir = det_pylibdir()
            self.log.debug("Python library dir: %s" % self.pylibdir)
            # on (some) multilib systems, the platform-specific library directory for the system Python is different
            # cfr. http://serverfault.com/a/88739/126446
            # so, we keep a list of different Python lib directories to take into account
            self.all_pylibdirs = nub([self.pylibdir, det_pylibdir(plat_specific=True)])
            self.log.debug("All Python library dirs: %s" % self.all_pylibdirs)

    def compose_install_command(self, prefix, extrapath=None):
        """Compose full install command."""
        cmd = []
        if extrapath:
            cmd.append(extrapath)

        cmd.extend([self.cfg['preinstallopts'], self.install_cmd, '--prefix=%s' % prefix, self.cfg['installopts']])

        if self.install_cmd_extra:
            cmd.append(self.install_cmd_extra)

        return ' '.join(cmd)

    def prerun(self):
        """Prepare extension by determining Python site lib dir."""
        super(PythonPackage, self).prerun()
        self.set_pylibdirs()

    def configure_step(self):
        """Configure Python package build."""
        # prepare easyblock by determining Python site lib dir(s)
        self.set_pylibdirs()

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
                raise EasyBuildError("Creating %s failed", self.sitecfgfn)

        # creates log entries for python being used, for debugging
        run_cmd("python -V", verbose=False)
        run_cmd("which python", verbose=False)
        run_cmd("python -c 'import sys; print(sys.executable)'", verbose=False)

        # don't add user site directory to sys.path (equivalent to python -s)
        # see https://www.python.org/dev/peps/pep-0370/
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)
        run_cmd("python -c 'import sys; print(sys.path)'", verbose=False)

    def build_step(self):
        """Build Python package using setup.py"""
        if not self.cfg.get('use_easy_install', False):
            cmd = "%s python setup.py build %s" % (self.cfg['prebuildopts'], self.cfg['buildopts'])
            run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Test the built Python package."""

        if isinstance(self.cfg['runtest'], basestring):
            self.testcmd = self.cfg['runtest']

        if self.cfg['runtest'] and not self.testcmd is None:
            extrapath = ""
            testinstalldir = None

            if self.testinstall:
                # install in test directory and export PYTHONPATH

                try:
                    testinstalldir = tempfile.mkdtemp()
                    for pylibdir in self.all_pylibdirs:
                        mkdir(os.path.join(testinstalldir, pylibdir), parents=True)
                except OSError, err:
                    raise EasyBuildError("Failed to create test install dir: %s", err)

                run_cmd("python -c 'import sys; print(sys.path)'", verbose=False)  # print Python search path (debug)
                abs_pylibdirs = [os.path.join(testinstalldir, pylibdir) for pylibdir in self.all_pylibdirs]
                extrapath = "export PYTHONPATH=%s &&" % os.pathsep.join(abs_pylibdirs + ['$PYTHONPATH'])

                cmd = self.compose_install_command(testinstalldir, extrapath=extrapath)
                run_cmd(cmd, log_all=True, simple=True, verbose=False)

            if self.testcmd:
                cmd = "%s%s" % (extrapath, self.testcmd)
                run_cmd(cmd, log_all=True, simple=True)

            if testinstalldir:
                try:
                    rmtree2(testinstalldir)
                except OSError, err:
                    raise EasyBuildError("Removing testinstalldir %s failed: %s", testinstalldir, err)

    def install_step(self):
        """Install Python package to a custom path using setup.py"""

        # mainly for debugging
        if self.install_cmd.startswith(EASY_INSTALL_CMD):
            run_cmd("%s --version" % EASY_INSTALL_CMD)

        # create expected directories
        abs_pylibdirs = [os.path.join(self.installdir, pylibdir) for pylibdir in self.all_pylibdirs]
        for pylibdir in abs_pylibdirs:
            mkdir(pylibdir, parents=True)

        # set PYTHONPATH as expected
        pythonpath = os.getenv('PYTHONPATH')
        new_pythonpath = os.pathsep.join([x for x in abs_pylibdirs + [pythonpath] if x is not None])
        env.setvar('PYTHONPATH', new_pythonpath, verbose=False)

        # actually install Python package
        cmd = self.compose_install_command(self.installdir)
        run_cmd(cmd, log_all=True, simple=True)

        # restore PYTHONPATH if it was set
        if pythonpath is not None:
            env.setvar('PYTHONPATH', pythonpath, verbose=False)

    def run(self, *args, **kwargs):
        """Perform the actual Python package build/installation procedure"""

        if not self.src:
            raise EasyBuildError("No source found for Python package %s, required for installation. (src: %s)",
                                 self.name, self.src)
        kwargs.update({'unpack_src': True})
        super(PythonPackage, self).run(*args, **kwargs)

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

    def make_module_req_guess(self):
        """
        Define list of subdirectories to consider for updating path-like environment variables ($PATH, etc.).
        """
        guesses = super(PythonPackage, self).make_module_req_guess()

        # avoid that lib subdirs are appended to $*LIBRARY_PATH if they don't provide libraries
        # typically, only lib/pythonX.Y/site-packages should be added to $PYTHONPATH (see make_module_extra)
        for envvar in ['LD_LIBRARY_PATH', 'LIBRARY_PATH']:
            newlist = []
            for subdir in guesses[envvar]:
                # only subdirectories that contain one or more files/libraries should be retained
                fullpath = os.path.join(self.installdir, subdir)
                if os.path.exists(fullpath) and any([os.path.isfile(x) for x in os.listdir(fullpath)]):
                    newlist.append(subdir)
            self.log.debug("Only retaining %s subdirs from %s for $%s (others don't provide any libraries)",
                           newlist, guesses[envvar], envvar)
            guesses[envvar] = newlist

        return guesses

    def make_module_extra(self, *args, **kwargs):
        """Add install path to PYTHONPATH"""
        txt = ''
        self.set_pylibdirs()
        for path in self.all_pylibdirs:
            fullpath = os.path.join(self.installdir, path)
            # only extend $PYTHONPATH with existing, non-empty directories
            if os.path.exists(fullpath) and os.listdir(fullpath):
                txt += self.module_generator.prepend_paths('PYTHONPATH', path)

        return super(PythonPackage, self).make_module_extra(txt, *args, **kwargs)
