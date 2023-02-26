##
# Copyright 2009-2023 Ghent University
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
EasyBuild support for Python packages, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Alexander Grund (TU Dresden)
"""
import json
import os
import re
import sys
import tempfile
from distutils.version import LooseVersion
from distutils.sysconfig import get_config_vars

import easybuild.tools.environment as env
from easybuild.base import fancylogger
from easybuild.easyblocks.python import EBPYTHONPREFIXES, EXTS_FILTER_PYTHON_PACKAGES
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.easyconfig.default import DEFAULT_CONFIG
from easybuild.framework.easyconfig.templates import TEMPLATE_CONSTANTS
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.config import build_option
from easybuild.tools.filetools import mkdir, remove_dir, which
from easybuild.tools.modules import get_software_root
from easybuild.tools.py2vs3 import string_type, subprocess_popen_text
from easybuild.tools.run import run_cmd
from easybuild.tools.utilities import nub
from easybuild.tools.hooks import CONFIGURE_STEP, BUILD_STEP, TEST_STEP, INSTALL_STEP


# not 'easy_install' deliberately, to avoid that pkg installations listed in easy-install.pth get preference
# '.' is required at the end when using easy_install/pip in unpacked source dir
EASY_INSTALL_TARGET = "easy_install"
PIP_INSTALL_CMD = "%(python)s -m pip install --prefix=%(prefix)s %(installopts)s %(loc)s"
SETUP_PY_INSTALL_CMD = "%(python)s setup.py %(install_target)s --prefix=%(prefix)s %(installopts)s"
UNKNOWN = 'UNKNOWN'


def det_python_version(python_cmd):
    """Determine version of specified 'python' command."""
    pycode = 'import sys; print("%s.%s.%s" % sys.version_info[:3])'
    out, _ = run_cmd("%s -c '%s'" % (python_cmd, pycode), simple=False, trace=False)
    return out.strip()


def pick_python_cmd(req_maj_ver=None, req_min_ver=None):
    """
    Pick 'python' command to use, based on specified version requirements.
    If the major version is specified, it must be an exact match (==).
    If the minor version is specified, it is considered a minimal minor version (>=).

    List of considered 'python' commands (in order)
    * 'python' available through $PATH
    * 'python<major_ver>' available through $PATH
    * 'python<major_ver>.<minor_ver>' available through $PATH
    * Python executable used in current session (sys.executable)
    """
    log = fancylogger.getLogger('pick_python_cmd', fname=False)

    def check_python_cmd(python_cmd):
        """Check whether specified Python command satisfies requirements."""

        # check whether specified Python command is available
        if os.path.isabs(python_cmd):
            if not os.path.isfile(python_cmd):
                log.debug("Python command '%s' does not exist", python_cmd)
                return False
        else:
            python_cmd_path = which(python_cmd)
            if python_cmd_path is None:
                log.debug("Python command '%s' not available through $PATH", python_cmd)
                return False

        if req_maj_ver is not None:
            if req_min_ver is None:
                req_majmin_ver = '%s.0' % req_maj_ver
            else:
                req_majmin_ver = '%s.%s' % (req_maj_ver, req_min_ver)

            pyver = det_python_version(python_cmd)

            # (strict) check for major version
            maj_ver = pyver.split('.')[0]
            if maj_ver != str(req_maj_ver):
                log.debug("Major Python version does not match: %s vs %s", maj_ver, req_maj_ver)
                return False

            # check for minimal minor version
            if LooseVersion(pyver) < LooseVersion(req_majmin_ver):
                log.debug("Minimal requirement for minor Python version not satisfied: %s vs %s", pyver, req_majmin_ver)
                return False

        # all check passed
        log.debug("All check passed for Python command '%s'!", python_cmd)
        return True

    # compose list of 'python' commands to consider
    python_cmds = ['python']
    if req_maj_ver:
        python_cmds.append('python%s' % req_maj_ver)
        if req_min_ver:
            python_cmds.append('python%s.%s' % (req_maj_ver, req_min_ver))
    python_cmds.append(sys.executable)
    log.debug("Considering Python commands: %s", ', '.join(python_cmds))

    # try and find a 'python' command that satisfies the requirements
    res = None
    for python_cmd in python_cmds:
        if check_python_cmd(python_cmd):
            log.debug("Python command '%s' satisfies version requirements!", python_cmd)
            if os.path.isabs(python_cmd):
                res = python_cmd
            else:
                res = which(python_cmd)
            log.debug("Absolute path to retained Python command: %s", res)
            break
        else:
            log.debug("Python command '%s' does not satisfy version requirements (maj: %s, min: %s), moving on",
                      python_cmd, req_maj_ver, req_min_ver)

    return res


def det_pylibdir(plat_specific=False, python_cmd=None):
    """Determine Python library directory."""
    log = fancylogger.getLogger('det_pylibdir', fname=False)

    if python_cmd is None:
        # use 'python' that is listed first in $PATH if none was specified
        python_cmd = 'python'

    # determine Python lib dir via distutils
    # use run_cmd, we can to talk to the active Python, not the system Python running EasyBuild
    prefix = '/tmp/'
    args = 'plat_specific=%s, prefix="%s"' % (plat_specific, prefix)
    pycode = "import distutils.sysconfig; print(distutils.sysconfig.get_python_lib(%s))" % args
    cmd = "%s -c '%s'" % (python_cmd, pycode)

    log.debug("Determining Python library directory using command '%s'", cmd)

    out, ec = run_cmd(cmd, simple=False, force_in_dry_run=True, trace=False)
    txt = out.strip().split('\n')[-1]

    # value obtained should start with specified prefix, otherwise something is very wrong
    if not txt.startswith(prefix):
        raise EasyBuildError("Last line of output of %s does not start with specified prefix %s: %s (exit code %s)",
                             cmd, prefix, out, ec)

    pylibdir = txt[len(prefix):]
    log.debug("Determined pylibdir using '%s': %s", cmd, pylibdir)
    return pylibdir


def get_pylibdirs(python_cmd):
    """Return a list of python library paths to use. The first entry will be the main one"""
    log = fancylogger.getLogger('get_pylibdirs', fname=False)

    # pylibdir is the 'main' Python lib directory
    pylibdir = det_pylibdir(python_cmd=python_cmd)
    log.debug("Python library dir: %s" % pylibdir)

    # on (some) multilib systems, the platform-specific library directory for the system Python is different
    # cfr. http://serverfault.com/a/88739/126446
    # so, we keep a list of different Python lib directories to take into account
    all_pylibdirs = nub([pylibdir, det_pylibdir(plat_specific=True, python_cmd=python_cmd)])
    log.debug("All Python library dirs: %s" % all_pylibdirs)

    # make very sure an entry starting with lib/ is present,
    # since older versions of setuptools hardcode 'lib' rather than using the value produced by
    # distutils.sysconfig.get_python_lib (which may always be lib64/...)
    if not any(pylibdir.startswith('lib' + os.path.sep) for pylibdir in all_pylibdirs):
        pylibdir = os.path.join('lib', *pylibdir.split(os.path.sep)[1:])
        all_pylibdirs.append(pylibdir)
        log.debug("No lib/ entry found in list of Python lib dirs, so added it: %s", all_pylibdirs)
    return all_pylibdirs


def det_pip_version(python_cmd='python'):
    """Determine version of currently active 'pip' module."""

    pip_version = None
    log = fancylogger.getLogger('det_pip_version', fname=False)
    log.info("Determining pip version...")

    out, _ = run_cmd("%s -m pip --version" % python_cmd, verbose=False, simple=False, trace=False)

    pip_version_regex = re.compile('^pip ([0-9.]+)')
    res = pip_version_regex.search(out)
    if res:
        pip_version = res.group(1)
        log.info("Found pip version: %s", pip_version)
    else:
        log.warning("Failed to determine pip version from '%s' using pattern '%s'", out, pip_version_regex.pattern)

    return pip_version


class PythonPackage(ExtensionEasyBlock):
    """Builds and installs a Python package, and provides a dedicated module file."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Easyconfig parameters specific to Python packages."""
        if extra_vars is None:
            extra_vars = {}
        extra_vars.update({
            'buildcmd': [None, "Command for building the package (e.g. for custom builds resulting in a whl file). "
                               "When using setup.py this will be passed to setup.py and defaults to 'build'. "
                               "Otherwise it will be used as-is. A value of None then skips the build step. "
                               "The template %(python)s will be replace by the currently used Python binary.", CUSTOM],
            'check_ldshared': [None, 'Check Python value of $LDSHARED, correct if needed to "$CC -shared"', CUSTOM],
            'download_dep_fail': [None, "Fail if downloaded dependencies are detected", CUSTOM],
            'install_src': [None, "Source path to pass to the install command (e.g. a whl file)."
                                  "Defaults to '.' for unpacked sources or the first source file specified", CUSTOM],
            'install_target': ['install', "Option to pass to setup.py", CUSTOM],
            'pip_ignore_installed': [True, "Let pip ignore installed Python packages (i.e. don't remove them)", CUSTOM],
            'pip_no_index': [None, "Pass --no-index to pip to disable connecting to PyPi entirely which also disables "
                                   "the pip version check. Enabled by default when pip_ignore_installed=True", CUSTOM],
            'req_py_majver': [None, "Required major Python version (only relevant when using system Python)", CUSTOM],
            'req_py_minver': [None, "Required minor Python version (only relevant when using system Python)", CUSTOM],
            'sanity_pip_check': [False, "Run 'python -m pip check' to ensure all required Python packages are "
                                        "installed and check for any package with an invalid (0.0.0) version.", CUSTOM],
            'runtest': [True, "Run unit tests.", CUSTOM],  # overrides default
            'testinstall': [False, "Install into temporary directory prior to running the tests.", CUSTOM],
            'unpack_sources': [None, "Unpack sources prior to build/install. Defaults to 'True' except for whl files",
                               CUSTOM],
            # A version of 0.0.0 is usually an error on installation unless the package does really not provide a
            # version. Those would fail the (extended) sanity_pip_check. So as a last resort they can be added here
            # and will be excluded from that check. Note that the display name is required, i.e. from `pip list`.
            'unversioned_packages': [[], "List of packages that don't have a version at all, i.e. show 0.0.0", CUSTOM],
            'use_pip': [None, "Install using '%s'" % PIP_INSTALL_CMD, CUSTOM],
            'use_pip_editable': [False, "Install using 'pip install --editable'", CUSTOM],
            # see https://packaging.python.org/tutorials/installing-packages/#installing-setuptools-extras
            'use_pip_extras': [None, "String with comma-separated list of 'extras' to install via pip", CUSTOM],
            'use_pip_for_deps': [False, "Install dependencies using '%s'" % PIP_INSTALL_CMD, CUSTOM],
            'use_pip_requirement': [False, "Install using 'python -m pip install --requirement'. The sources is " +
                                           "expected to be the requirements file.", CUSTOM],
            'zipped_egg': [False, "Install as a zipped eggs", CUSTOM],
        })
        # Use PYPI_SOURCE as the default for source_urls.
        # As PyPi ignores the casing in the path part of the URL (but not the filename) we can always use PYPI_SOURCE.
        if 'source_urls' not in extra_vars:
            # Create a copy so the defaults are not modified by the following line
            src_urls = DEFAULT_CONFIG['source_urls'][:]
            src_urls[0] = [url for name, url, _ in TEMPLATE_CONSTANTS if name == 'PYPI_SOURCE']
            extra_vars['source_urls'] = src_urls

        return ExtensionEasyBlock.extra_options(extra_vars=extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize custom class variables."""
        super(PythonPackage, self).__init__(*args, **kwargs)

        self.sitecfg = None
        self.sitecfgfn = 'site.cfg'
        self.sitecfglibdir = None
        self.sitecfgincdir = None
        self.testinstall = self.cfg['testinstall']
        self.testcmd = None
        self.unpack_options = self.cfg['unpack_options']

        self.require_python = True
        self.python_cmd = None
        self.pylibdir = UNKNOWN
        self.all_pylibdirs = [UNKNOWN]

        self.install_cmd_output = ''

        # make sure there's no site.cfg in $HOME, because setup.py will find it and use it
        home = os.path.expanduser('~')
        if os.path.exists(os.path.join(home, 'site.cfg')):
            raise EasyBuildError("Found site.cfg in your home directory (%s), please remove it.", home)

        # use lowercase name as default value for expected module name (used in sanity check)
        if 'modulename' not in self.options:
            self.options['modulename'] = self.name.lower().replace('-', '_')
            self.log.info("Using default value for expected module name (lowercase software name): '%s'",
                          self.options['modulename'])

        # only for Python packages installed as extensions:
        # inherit setting for detection of downloaded dependencies from parent,
        # if 'download_dep_fail' was left unspecified
        if self.is_extension and self.cfg.get('download_dep_fail') is None:
            self.cfg['download_dep_fail'] = self.master.cfg['exts_download_dep_fail']
            self.log.info("Inherited setting for detection of downloaded dependencies from parent: %s",
                          self.cfg['download_dep_fail'])

        # figure out whether this Python package is being installed for multiple Python versions
        self.multi_python = 'Python' in self.cfg['multi_deps']

        # determine install command
        self.use_setup_py = False
        self.determine_install_command()

    def determine_install_command(self):
        """
        Determine install command to use.
        """
        if self.cfg.get('use_pip', False) or self.cfg.get('use_pip_editable', False):
            self.install_cmd = PIP_INSTALL_CMD

            if build_option('debug'):
                self.cfg.update('installopts', '--verbose')

            # don't auto-install dependencies with pip unless use_pip_for_deps=True
            # the default is use_pip_for_deps=False
            if self.cfg.get('use_pip_for_deps'):
                self.log.info("Using pip to also install the dependencies")
            else:
                self.log.info("Using pip with --no-deps option")
                self.cfg.update('installopts', '--no-deps')

            if self.cfg.get('pip_ignore_installed', True):
                # don't (try to) uninstall already availale versions of the package being installed
                self.cfg.update('installopts', '--ignore-installed')

            if self.cfg.get('zipped_egg', False):
                self.cfg.update('installopts', '--egg')

            pip_no_index = self.cfg.get('pip_no_index', None)
            if pip_no_index or (pip_no_index is None and self.cfg.get('download_dep_fail')):
                self.cfg.update('installopts', '--no-index')

            # avoid that pip (ab)uses $HOME/.cache/pip
            # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
            env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
            self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        else:
            self.use_setup_py = True
            self.install_cmd = SETUP_PY_INSTALL_CMD

            if self.cfg['install_target'] == EASY_INSTALL_TARGET:
                self.install_cmd += " %(loc)s"
                self.cfg.update('installopts', '--no-deps')
            if self.cfg.get('zipped_egg', False):
                if self.cfg['install_target'] == EASY_INSTALL_TARGET:
                    self.cfg.update('installopts', '--zip-ok')
                else:
                    raise EasyBuildError("Installing zipped eggs requires using easy_install or pip")

        self.log.info("Using '%s' as install command", self.install_cmd)

    def set_pylibdirs(self):
        """Set Python lib directory-related class variables."""

        self.all_pylibdirs = get_pylibdirs(python_cmd=self.python_cmd)
        self.pylibdir = self.all_pylibdirs[0]

    def prepare_python(self):
        """Python-specific preparations."""

        # pick 'python' command to use
        python = None
        python_root = get_software_root('Python')
        # keep in mind that Python may be listed as an allowed system dependency,
        # so just checking Python root is not sufficient
        if python_root:
            bin_python = os.path.join(python_root, 'bin', 'python')
            if os.path.exists(bin_python) and os.path.samefile(which('python'), bin_python):
                # if Python is listed as a (build) dependency, use 'python' command provided that way
                python = os.path.join(python_root, 'bin', 'python')
                self.log.debug("Retaining 'python' command for Python dependency: %s", python)

        if python is None:
            # if no Python version requirements are specified,
            # use major/minor version of Python being used in this EasyBuild session
            req_py_majver = self.cfg['req_py_majver']
            if req_py_majver is None:
                req_py_majver = sys.version_info[0]
            req_py_minver = self.cfg['req_py_minver']
            if req_py_minver is None:
                req_py_minver = sys.version_info[1]

            # if using system Python, go hunting for a 'python' command that satisfies the requirements
            python = pick_python_cmd(req_maj_ver=req_py_majver, req_min_ver=req_py_minver)

        if python:
            self.python_cmd = python
            self.log.info("Python command being used: %s", self.python_cmd)
        elif self.require_python:
            raise EasyBuildError("Failed to pick Python command to use")
        else:
            self.log.warning("No Python command found!")

        if self.python_cmd:
            # set Python lib directories
            self.set_pylibdirs()

    def _should_unpack_source(self):
        """Determine whether we need to unpack the source(s)"""

        unpack_sources = self.cfg.get('unpack_sources')

        # if unpack_sources is not specified, check file extension of (first) source file
        if unpack_sources is None:
            src = self.src
            # we may have a list of sources, only consider first source file in that case
            if isinstance(src, (list, tuple)):
                if src:
                    src = src[0]
                    # source file specs (incl. path) could be specified via a dict
                    if isinstance(src, dict) and 'path' in src:
                        src = src['path']
                else:
                    unpack_sources = False

            # if undecided, check the source file extension: don't try to unpack wheels (*.whl)
            if unpack_sources is None:
                _, ext = os.path.splitext(src)
                unpack_sources = ext.lower() != '.whl'

        return unpack_sources

    def get_installed_python_packages(self, names_only=True, python_cmd=None):
        """Return list of Python packages that are installed

        When names_only is True then only the names are returned, else the full info from `pip list`.
        Note that the names are reported by pip and might be different to the name that need to be used to import it
        """
        if python_cmd is None:
            python_cmd = self.python_cmd
        # Check installed python packages but only check stdout, not stderr which might contain user facing warnings
        cmd_list = [python_cmd, '-m', 'pip', 'list', '--isolated', '--disable-pip-version-check',
                    '--format', 'json']
        full_cmd = ' '.join(cmd_list)
        self.log.info("Running command '%s'" % full_cmd)
        proc = subprocess_popen_text(cmd_list, env=os.environ)
        (stdout, stderr) = proc.communicate()
        ec = proc.returncode
        msg = "Command '%s' returned with %s: stdout: %s; stderr: %s" % (full_cmd, ec, stdout, stderr)
        if ec:
            self.log.info(msg)
            raise EasyBuildError('Failed to determine installed python packages: %s', stderr)

        self.log.debug(msg)
        pkgs = json.loads(stdout.strip())
        if names_only:
            return [pkg['name'] for pkg in pkgs]
        else:
            return pkgs

    def compose_install_command(self, prefix, extrapath=None, installopts=None):
        """Compose full install command."""

        using_pip = self.install_cmd.startswith(PIP_INSTALL_CMD)
        if using_pip:

            pip_version = det_pip_version(python_cmd=self.python_cmd)
            if pip_version:
                # pip 8.x or newer required, because of --prefix option being used
                if LooseVersion(pip_version) >= LooseVersion('8.0'):
                    self.log.info("Found pip version %s, OK", pip_version)
                else:
                    raise EasyBuildError("Need pip version 8.0 or newer, found version %s", pip_version)

                # pip 10.x introduced a nice new "build isolation" feature (enabled by default),
                # which will download and install in a list of build dependencies specified in a pyproject.toml file
                # (see also https://pip.pypa.io/en/stable/reference/pip/#pep-517-and-518-support);
                # since we provide all required dependencies already, we disable this via --no-build-isolation
                if LooseVersion(pip_version) >= LooseVersion('10.0'):
                    if '--no-build-isolation' not in self.cfg['installopts']:
                        self.cfg.update('installopts', '--no-build-isolation')

            elif not self.dry_run:
                raise EasyBuildError("Failed to determine pip version!")

        cmd = []
        if extrapath:
            cmd.append(extrapath)

        loc = self.cfg.get('install_src')
        if not loc:
            if self._should_unpack_source():
                # specify current directory
                loc = '.'
            elif isinstance(self.src, string_type):
                # for extensions, self.src specifies the location of the source file
                loc = self.src
            else:
                # otherwise, self.src is a list of dicts, one element per source file
                loc = self.src[0]['path']

        if using_pip:
            extras = self.cfg.get('use_pip_extras')
            if extras:
                loc += '[%s]' % extras

        if installopts is None:
            installopts = self.cfg['installopts']

        if self.cfg.get('use_pip_editable', False):
            # add --editable option when requested, in the right place (i.e. right before the location specification)
            loc = "--editable %s" % loc

        if self.cfg.get('use_pip_requirement', False):
            # add --requirement option when requested, in the right place (i.e. right before the location specification)
            loc = "--requirement %s" % loc

        cmd.extend([
            self.cfg['preinstallopts'],
            self.install_cmd % {
                'installopts': installopts,
                'install_target': self.cfg['install_target'],
                'loc': loc,
                'prefix': prefix,
                'python': self.python_cmd,
            },
        ])

        return ' '.join(cmd)

    def extract_step(self):
        """Unpack source files, unless instructed otherwise."""
        if self._should_unpack_source():
            super(PythonPackage, self).extract_step()

    def prerun(self):
        """Prepare for installing Python package."""
        super(PythonPackage, self).prerun()
        self.prepare_python()

    def prepare_step(self, *args, **kwargs):
        """Prepare for building and installing this Python package."""
        super(PythonPackage, self).prepare_step(*args, **kwargs)
        self.prepare_python()

    def configure_step(self):
        """Configure Python package build/install."""

        # don't add user site directory to sys.path (equivalent to python -s)
        # see https://www.python.org/dev/peps/pep-0370/
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)

        if self.python_cmd is None:
            self.prepare_python()

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

        # conservatively auto-enable checking of $LDSHARED if it is not explicitely enabled or disabled
        # only do this for sufficiently recent Python versions (>= 3.7 or Python 2.x >= 2.7.15)
        if self.cfg.get('check_ldshared') is None:
            pyver = det_python_version(self.python_cmd)
            recent_py2 = pyver.startswith('2') and LooseVersion(pyver) >= LooseVersion('2.7.15')
            if recent_py2 or LooseVersion(pyver) >= LooseVersion('3.7'):
                self.log.info("Checking of $LDSHARED auto-enabled for sufficiently recent Python version %s", pyver)
                self.cfg['check_ldshared'] = True
            else:
                self.log.info("Not auto-enabling checking of $LDSHARED, Python version %s is not recent enough", pyver)

        # ensure that LDSHARED uses CC
        if self.cfg.get('check_ldshared', False):
            curr_cc = os.getenv('CC')
            python_ldshared = get_config_vars('LDSHARED')[0]
            if python_ldshared and curr_cc:
                if python_ldshared.split(' ')[0] == curr_cc:
                    self.log.info("Python's value for $LDSHARED ('%s') uses current $CC value ('%s'), not touching it",
                                  python_ldshared, curr_cc)
                else:
                    self.log.info("Python's value for $LDSHARED ('%s') doesn't use current $CC value ('%s'), fixing",
                                  python_ldshared, curr_cc)
                    env.setvar("LDSHARED", curr_cc + " -shared")
            else:
                if curr_cc:
                    self.log.info("No $LDSHARED found for Python, setting to '%s -shared'", curr_cc)
                    env.setvar("LDSHARED", curr_cc + " -shared")
                else:
                    self.log.info("No value set for $CC, so not touching $LDSHARED either")

        # creates log entries for python being used, for debugging
        cmd = "%(python)s -V; %(python)s -c 'import sys; print(sys.executable, sys.path)'"
        run_cmd(cmd % {'python': self.python_cmd}, verbose=False, trace=False)

    def build_step(self):
        """Build Python package using setup.py"""
        build_cmd = self.cfg['buildcmd']
        if self.use_setup_py:

            if get_software_root('CMake'):
                include_paths = os.pathsep.join(self.toolchain.get_variable("CPPFLAGS", list))
                library_paths = os.pathsep.join(self.toolchain.get_variable("LDFLAGS", list))
                env.setvar("CMAKE_INCLUDE_PATH", include_paths)
                env.setvar("CMAKE_LIBRARY_PATH", library_paths)

            if not build_cmd:
                build_cmd = 'build'  # Default value for setup.py
            build_cmd = '%(python)s setup.py ' + build_cmd

        if build_cmd:
            build_cmd = build_cmd % {'python': self.python_cmd}
            cmd = ' '.join([self.cfg['prebuildopts'], build_cmd, self.cfg['buildopts']])
            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            # keep track of all output, so we can check for auto-downloaded dependencies;
            # take into account that build/install steps may be run multiple times
            # We consider the build and install output together as downloads likely happen here if this is run
            self.install_cmd_output += out

    def test_step(self, return_output_ec=False):
        """
        Test the built Python package.

        :param return_output: return output and exit code of test command
        """

        if isinstance(self.cfg['runtest'], string_type):
            self.testcmd = self.cfg['runtest']

        if self.cfg['runtest'] and self.testcmd is not None:
            extrapath = ""
            testinstalldir = None

            out, ec = (None, None)

            if self.testinstall:
                # install in test directory and export PYTHONPATH

                try:
                    testinstalldir = tempfile.mkdtemp()
                    for pylibdir in self.all_pylibdirs:
                        mkdir(os.path.join(testinstalldir, pylibdir), parents=True)
                except OSError as err:
                    raise EasyBuildError("Failed to create test install dir: %s", err)

                # print Python search path (just debugging purposes)
                run_cmd("%s -c 'import sys; print(sys.path)'" % self.python_cmd, verbose=False, trace=False)

                abs_pylibdirs = [os.path.join(testinstalldir, pylibdir) for pylibdir in self.all_pylibdirs]
                extrapath = "export PYTHONPATH=%s &&" % os.pathsep.join(abs_pylibdirs + ['$PYTHONPATH'])

                cmd = self.compose_install_command(testinstalldir, extrapath=extrapath)
                run_cmd(cmd, log_all=True, simple=True, verbose=False)

            if self.testcmd:
                testcmd = self.testcmd % {'python': self.python_cmd}
                cmd = ' '.join([
                    extrapath,
                    self.cfg['pretestopts'],
                    testcmd,
                    self.cfg['testopts'],
                ])

                if return_output_ec:
                    (out, ec) = run_cmd(cmd, log_all=False, log_ok=False, simple=False, regexp=False)
                    # need to log seperately, since log_all and log_ok need to be false to retrieve out and ec
                    self.log.info("cmd '%s' exited with exit code %s and output:\n%s", cmd, ec, out)
                else:
                    run_cmd(cmd, log_all=True, simple=True)

            if testinstalldir:
                remove_dir(testinstalldir)

            if return_output_ec:
                return (out, ec)

    def install_step(self):
        """Install Python package to a custom path using setup.py"""

        # create expected directories
        abs_pylibdirs = [os.path.join(self.installdir, pylibdir) for pylibdir in self.all_pylibdirs]
        for pylibdir in abs_pylibdirs:
            mkdir(pylibdir, parents=True)

        abs_bindir = os.path.join(self.installdir, 'bin')

        # set PYTHONPATH and PATH as expected
        old_values = dict()
        for name, new_values in (('PYTHONPATH', abs_pylibdirs), ('PATH', [abs_bindir])):
            old_value = os.getenv(name)
            old_values[name] = old_value
            new_value = os.pathsep.join(new_values + ([old_value] if old_value else []))
            if new_value:
                env.setvar(name, new_value, verbose=False)

        # actually install Python package
        cmd = self.compose_install_command(self.installdir)
        (out, _) = run_cmd(cmd, log_all=True, log_ok=True, simple=False)

        # keep track of all output from install command, so we can check for auto-downloaded dependencies;
        # take into account that install step may be run multiple times
        # (for iterated installations over multiply Python versions)
        self.install_cmd_output += out

        # fix shebangs if specified
        self.fix_shebang()

        # restore env vars if it they were set
        for name in ('PYTHONPATH', 'PATH'):
            value = old_values[name]
            if value is not None:
                env.setvar(name, value, verbose=False)

    def run(self, *args, **kwargs):
        """Perform the actual Python package build/installation procedure"""

        if not self.src:
            raise EasyBuildError("No source found for Python package %s, required for installation. (src: %s)",
                                 self.name, self.src)
        # we unpack unless explicitly told otherwise
        kwargs.setdefault('unpack_src', self._should_unpack_source())
        super(PythonPackage, self).run(*args, **kwargs)

        # configure, build, test, install
        # See EasyBlock.get_steps
        steps = [
            (CONFIGURE_STEP, 'configuring', [lambda x: x.configure_step], True),
            (BUILD_STEP, 'building', [lambda x: x.build_step], True),
            (TEST_STEP, 'testing', [lambda x: x._test_step], True),
            (INSTALL_STEP, "installing", [lambda x: x.install_step], True),
        ]
        self.skip = False  # --skip does not apply here
        self.silent = build_option('silent')
        # See EasyBlock.run_all_steps
        for (step_name, descr, step_methods, skippable) in steps:
            if self.skip_step(step_name, skippable):
                print_msg("\t%s [skipped]" % descr, log=self.log, silent=self.silent)
            else:
                if self.dry_run:
                    self.dry_run_msg("\t%s... [DRY RUN]\n", descr)
                else:
                    print_msg("\t%s..." % descr, log=self.log, silent=self.silent)
                    for step_method in step_methods:
                        step_method(self)()

    def load_module(self, *args, **kwargs):
        """
        Make sure that $PYTHONNOUSERSITE is defined after loading module file for this software."""

        super(PythonPackage, self).load_module(*args, **kwargs)

        # don't add user site directory to sys.path (equivalent to python -s),
        # to avoid that any Python packages installed in $HOME/.local/lib affect the sanity check;
        # required here to ensure that it is defined for stand-alone installations,
        # because the environment is reset to the initial environment right before loading the module
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)

    def sanity_check_step(self, *args, **kwargs):
        """
        Custom sanity check for Python packages
        """

        success, fail_msg = True, ''

        # load module early ourselves rather than letting parent sanity_check_step method do so,
        # since custom actions taken below require that environment is set up properly already
        # (especially when using --sanity-check-only)
        if hasattr(self, 'sanity_check_module_loaded') and not self.sanity_check_module_loaded:
            extension = self.is_extension or kwargs.get('extension', False)
            extra_modules = kwargs.get('extra_modules', None)
            self.fake_mod_data = self.sanity_check_load_module(extension=extension, extra_modules=extra_modules)

        # don't add user site directory to sys.path (equivalent to python -s)
        # see https://www.python.org/dev/peps/pep-0370/;
        # must be set here to ensure that it is defined when running sanity check for extensions,
        # since load_module is not called for every extension,
        # to avoid that any Python packages installed in $HOME/.local/lib affect the sanity check;
        # see also https://github.com/easybuilders/easybuild-easyblocks/issues/1877
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)

        if self.cfg.get('download_dep_fail', False):
            self.log.info("Detection of downloaded depenencies enabled, checking output of installation command...")
            patterns = [
                'Downloading .*/packages/.*',  # setuptools
                r'Collecting .*',  # pip
            ]
            downloaded_deps = []
            for pattern in patterns:
                downloaded_deps.extend(re.compile(pattern, re.M).findall(self.install_cmd_output))

            if downloaded_deps:
                success = False
                fail_msg = "found one or more downloaded dependencies: %s" % ', '.join(downloaded_deps)
                self.sanity_check_fail_msgs.append(fail_msg)
        else:
            self.log.debug("Detection of downloaded dependencies not enabled")

        # inject directory path that uses %(pyshortver)s template into default value for sanity_check_paths,
        # but only for stand-alone installations, not for extensions;
        # this is relevant for installations of Python packages for multiple Python versions (via multi_deps)
        # (we can not pass this via custom_paths, since then the %(pyshortver)s template value will not be resolved)
        if not self.is_extension and not self.cfg['sanity_check_paths'] and kwargs.get('custom_paths') is None:
            self.cfg['sanity_check_paths'] = {
                'files': [],
                'dirs': [os.path.join('lib', 'python%(pyshortver)s', 'site-packages')],
            }

        # make sure 'exts_filter' is defined, which is used for sanity check
        if self.multi_python:
            # when installing for multiple Python versions, we must use 'python', not a full-path 'python' command!
            python_cmd = 'python'
            if 'exts_filter' not in kwargs:
                kwargs.update({'exts_filter': EXTS_FILTER_PYTHON_PACKAGES})
        else:
            # 'python' is replaced by full path to active 'python' command
            # (which is required especially when installing with system Python)
            if self.python_cmd is None:
                self.prepare_python()
            python_cmd = self.python_cmd
            if 'exts_filter' not in kwargs:
                orig_exts_filter = EXTS_FILTER_PYTHON_PACKAGES
                exts_filter = (orig_exts_filter[0].replace('python', self.python_cmd), orig_exts_filter[1])
                kwargs.update({'exts_filter': exts_filter})

        if self.cfg.get('sanity_pip_check', False):
            pip_version = det_pip_version(python_cmd=python_cmd)

            if pip_version:
                pip_check_command = "%s -m pip check" % python_cmd

                if LooseVersion(pip_version) >= LooseVersion('9.0.0'):

                    if not self.is_extension:
                        # for stand-alone Python package installations (not part of a bundle of extensions),
                        # the (fake or real) module file must be loaded at this point,
                        # otherwise the Python package being installed is not "in view",
                        # and we will overlook missing dependencies...
                        loaded_modules = [x['mod_name'] for x in self.modules_tool.list()]
                        if self.short_mod_name not in loaded_modules:
                            self.log.debug("Currently loaded modules: %s", loaded_modules)
                            raise EasyBuildError("%s module is not loaded, this should never happen...",
                                                 self.short_mod_name)

                    pip_check_errors = []

                    pip_check_msg, ec = run_cmd(pip_check_command, log_ok=False)
                    if ec:
                        pip_check_errors.append('`%s` failed:\n%s' % (pip_check_command, pip_check_msg))
                    else:
                        self.log.info('`%s` completed successfully' % pip_check_command)

                    # Also check for a common issue where the package version shows up as 0.0.0 often caused
                    # by using setup.py as the installation method for a package which is released as a generic wheel
                    # named name-version-py2.py3-none-any.whl. `tox` creates those from version controlled source code
                    # so it will contain a version, but the raw tar.gz does not.
                    pkgs = self.get_installed_python_packages(names_only=False, python_cmd=python_cmd)
                    faulty_version = '0.0.0'
                    faulty_pkg_names = [pkg['name'] for pkg in pkgs if pkg['version'] == faulty_version]

                    for unversioned_package in self.cfg.get('unversioned_packages', []):
                        try:
                            faulty_pkg_names.remove(unversioned_package)
                            self.log.debug('Excluding unversioned package %s from check', unversioned_package)
                        except ValueError:
                            try:
                                version = next(pkg['version'] for pkg in pkgs if pkg['name'] == unversioned_package)
                            except StopIteration:
                                msg = ('Package %s in unversioned_packages was not found in the installed packages. '
                                       'Check that the name from `python -m pip list` is used which may be different '
                                       'than the module name.' % unversioned_package)
                            else:
                                msg = ('Package %s in unversioned_packages has a version of %s which is valid. '
                                       'Please remove it from unversioned_packages.' % (unversioned_package, version))
                            pip_check_errors.append(msg)

                    self.log.info('Found %s invalid packages out of %s packages', len(faulty_pkg_names), len(pkgs))
                    if faulty_pkg_names:
                        msg = (
                            "The following Python packages were likely not installed correctly because they show a "
                            "version of '%s':\n%s\n"
                            "This may be solved by using a *-none-any.whl file as the source instead. "
                            "See e.g. the SOURCE*_WHL templates.\n"
                            "Otherwise you could check if the package provides a version at all or if e.g. poetry is "
                            "required (check the source for a pyproject.toml and see PEP517 for details on that)."
                         ) % (faulty_version, '\n'.join(faulty_pkg_names))
                        pip_check_errors.append(msg)

                    if pip_check_errors:
                        raise EasyBuildError('\n'.join(pip_check_errors))
                else:
                    raise EasyBuildError("pip >= 9.0.0 is required for running '%s', found %s",
                                         pip_check_command,
                                         pip_version)
            else:
                raise EasyBuildError("Failed to determine pip version!")

        parent_success, parent_fail_msg = super(PythonPackage, self).sanity_check_step(*args, **kwargs)

        if parent_fail_msg:
            parent_fail_msg += ', '

        return (parent_success and success, parent_fail_msg + fail_msg)

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
                if os.path.exists(fullpath):
                    if any([os.path.isfile(os.path.join(fullpath, x)) for x in os.listdir(fullpath)]):
                        newlist.append(subdir)
            self.log.debug("Only retaining %s subdirs from %s for $%s (others don't provide any libraries)",
                           newlist, guesses[envvar], envvar)
            guesses[envvar] = newlist

        return guesses

    def make_module_extra(self, *args, **kwargs):
        """Add install path to PYTHONPATH"""
        txt = ''

        # update $EBPYTHONPREFIXES rather than $PYTHONPATH
        # if this Python package was installed for multiple Python versions
        if self.multi_python:
            txt += self.module_generator.prepend_paths(EBPYTHONPREFIXES, '')
        elif self.require_python:
            self.set_pylibdirs()
            for path in self.all_pylibdirs:
                fullpath = os.path.join(self.installdir, path)
                # only extend $PYTHONPATH with existing, non-empty directories
                if os.path.exists(fullpath) and os.listdir(fullpath):
                    txt += self.module_generator.prepend_paths('PYTHONPATH', path)

        return super(PythonPackage, self).make_module_extra(txt, *args, **kwargs)
