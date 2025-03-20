##
# Copyright 2009-2025 Ghent University
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
import glob
import json
import os
import re
import sys
import tempfile
from easybuild.tools import LooseVersion
from sysconfig import get_config_vars

import easybuild.tools.environment as env
from easybuild.base import fancylogger
from easybuild.easyblocks.python import EXTS_FILTER_PYTHON_PACKAGES
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.easyconfig.default import DEFAULT_CONFIG
from easybuild.framework.easyconfig.templates import PYPI_SOURCE
from easybuild.framework.extensioneasyblock import ExtensionEasyBlock
from easybuild.tools.build_log import EasyBuildError, print_msg
from easybuild.tools.config import build_option, PYTHONPATH, EBPYTHONPREFIXES
from easybuild.tools.filetools import change_dir, mkdir, remove_dir, symlink, which
from easybuild.tools.modules import ModEnvVarType, get_software_root
from easybuild.tools.run import run_shell_cmd, subprocess_popen_text
from easybuild.tools.utilities import nub
from easybuild.tools.hooks import CONFIGURE_STEP, BUILD_STEP, TEST_STEP, INSTALL_STEP


# not 'easy_install' deliberately, to avoid that pkg installations listed in easy-install.pth get preference
# '.' is required at the end when using easy_install/pip in unpacked source dir
EASY_INSTALL_TARGET = "easy_install"
PIP_INSTALL_CMD = "%(python)s -m pip install --prefix=%(prefix)s %(installopts)s %(loc)s"
SETUP_PY_INSTALL_CMD = "%(python)s setup.py %(install_target)s --prefix=%(prefix)s %(installopts)s"
UNKNOWN = 'UNKNOWN'

# Python installation schemes, see https://docs.python.org/3/library/sysconfig.html#installation-paths;
# posix_prefix is the default upstream installation scheme (and the want to want)
PY_INSTALL_SCHEME_POSIX_PREFIX = 'posix_prefix'
# posix_local is custom installation scheme on Debian/Ubuntu which implies additional action,
# see https://github.com/easybuilders/easybuild-easyblocks/issues/2976
PY_INSTALL_SCHEME_POSIX_LOCAL = 'posix_local'
PY_INSTALL_SCHEMES = [
    PY_INSTALL_SCHEME_POSIX_PREFIX,
    PY_INSTALL_SCHEME_POSIX_LOCAL,
]


def det_python_version(python_cmd):
    """Determine version of specified 'python' command."""
    pycode = 'import sys; print("%s.%s.%s" % sys.version_info[:3])'
    res = run_shell_cmd("%s -c '%s'" % (python_cmd, pycode), hidden=True)
    return res.output.strip()


def pick_python_cmd(req_maj_ver=None, req_min_ver=None, max_py_majver=None, max_py_minver=None):
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
                log.debug(f"Python command '{python_cmd}' does not exist")
                return False
        else:
            python_cmd_path = which(python_cmd)
            if python_cmd_path is None:
                log.debug(f"Python command '{python_cmd}' not available through $PATH")
                return False

        pyver = det_python_version(python_cmd)

        if req_maj_ver is not None:
            if req_min_ver is None:
                req_majmin_ver = '%s.0' % req_maj_ver
            else:
                req_majmin_ver = '%s.%s' % (req_maj_ver, req_min_ver)

            # (strict) check for major version
            maj_ver = pyver.split('.')[0]
            if maj_ver != str(req_maj_ver):
                log.debug(f"Major Python version does not match: {maj_ver} vs {req_maj_ver}")
                return False

            # check for minimal minor version
            if LooseVersion(pyver) < LooseVersion(req_majmin_ver):
                log.debug(f"Minimal requirement for minor Python version not satisfied: {pyver} vs {req_majmin_ver}")
                return False

        if max_py_majver is not None:
            if max_py_minver is None:
                max_majmin_ver = '%s.0' % max_py_majver
            else:
                max_majmin_ver = '%s.%s' % (max_py_majver, max_py_minver)

            if LooseVersion(pyver) > LooseVersion(max_majmin_ver):
                log.debug("Python version (%s) on the system is newer than the maximum supported "
                          "Python version specified in the easyconfig (%s)",
                          pyver, max_majmin_ver)
                return False

        # all check passed
        log.debug(f"All check passed for Python command '{python_cmd}'!")
        return True

    # compose list of 'python' commands to consider
    python_cmds = ['python']
    if req_maj_ver:
        python_cmds.append(f'python{req_maj_ver}')
        if req_min_ver:
            python_cmds.append(f'python{req_maj_ver}.{req_min_ver}')
    python_cmds.append(sys.executable)
    log.debug("Considering Python commands: " + ', '.join(python_cmds))

    # try and find a 'python' command that satisfies the requirements
    res = None
    for python_cmd in python_cmds:
        if check_python_cmd(python_cmd):
            log.debug(f"Python command '{python_cmd}' satisfies version requirements!")
            if os.path.isabs(python_cmd):
                res = python_cmd
            else:
                res = which(python_cmd)
            log.debug("Absolute path to retained Python command: " + res)
            break
        else:
            log.debug(f"Python command '{python_cmd}' does not satisfy version requirements "
                      f"(maj: {req_maj_ver}, min: {req_min_ver}), moving on")

    return res


def find_python_cmd(log, req_py_majver, req_py_minver, max_py_majver, max_py_minver, required):
    """Return an appropriate python command to use.

    When python is a dependency use the full path to that.
    Else use req_py_maj/minver (defaulting to the Python being used in this EasyBuild session) to select one.
    If no (matching) python command is found and raise an Error or log a warning depending on the required argument.
    """
    python = None
    python_root = get_software_root('Python')
    # keep in mind that Python may be listed as an allowed system dependency,
    # so just checking Python root is not sufficient
    if python_root:
        bin_python = os.path.join(python_root, 'bin', 'python')
        if os.path.exists(bin_python) and os.path.samefile(which('python'), bin_python):
            # if Python is listed as a (build) dependency, use 'python' command provided that way
            python = bin_python
            log.debug("Retaining 'python' command for Python dependency: " + python)

    if python is None:
        # if no Python version requirements are specified,
        # use major/minor version of Python being used in this EasyBuild session
        if req_py_majver is None:
            req_py_majver = sys.version_info[0]
        if req_py_minver is None:
            req_py_minver = sys.version_info[1]
        # if using system Python, go hunting for a 'python' command that satisfies the requirements
        python = pick_python_cmd(req_maj_ver=req_py_majver, req_min_ver=req_py_minver,
                                 max_py_majver=max_py_majver, max_py_minver=max_py_minver)

    if python:
        log.info("Python command being used: " + python)
    elif required:
        if all(v is None for v in (req_py_majver, req_py_minver, max_py_majver, max_py_minver)):
            error_msg = "Failed to pick Python command to use"
        else:
            error_msg = (f"Failed to pick Python command that satisfies requirements in the easyconfig: "
                         f"req_py_majver = {req_py_majver}, req_py_minver = {req_py_minver}")
            if max_py_majver is not None:
                error_msg += f"max_py_majver = {max_py_majver}, max_py_minver = {max_py_minver}"
        raise EasyBuildError(error_msg)
    else:
        log.warning("No Python command found!")
    return python


def find_python_cmd_from_ec(log, cfg, required):
    """Find a python command using the constraints specified in the EasyConfig"""
    return find_python_cmd(log,
                           cfg['req_py_majver'], cfg['req_py_minver'],
                           max_py_majver=cfg['max_py_majver'],
                           max_py_minver=cfg['max_py_minver'],
                           required=required)


def det_pylibdir(plat_specific=False, python_cmd=None):
    """Determine Python library directory."""
    log = fancylogger.getLogger('det_pylibdir', fname=False)

    if python_cmd is None:
        # use 'python' that is listed first in $PATH if none was specified
        python_cmd = 'python'

    # determine Python lib dir via distutils
    # use run_shell_cmd, we can to talk to the active Python, not the system Python running EasyBuild
    prefix = '/tmp/'
    if LooseVersion(det_python_version(python_cmd)) >= LooseVersion('3.12'):
        # Python 3.12 removed distutils but has a core sysconfig module which is similar
        pathname = 'platlib' if plat_specific else 'purelib'
        vars_param = {'platbase': prefix, 'base': prefix}
        pycode = 'import sysconfig; print(sysconfig.get_path("%s", vars=%s))' % (pathname, vars_param)
    else:
        args = 'plat_specific=%s, prefix="%s"' % (plat_specific, prefix)
        pycode = "import distutils.sysconfig; print(distutils.sysconfig.get_python_lib(%s))" % args
    cmd = "%s -c '%s'" % (python_cmd, pycode.replace("'", '"'))

    log.debug("Determining Python library directory using command '%s'", cmd)

    res = run_shell_cmd(cmd, in_dry_run=True, hidden=True)
    txt = res.output.strip().split('\n')[-1]

    # value obtained should start with specified prefix, otherwise something is very wrong
    if not txt.startswith(prefix):
        raise EasyBuildError("Last line of output of %s does not start with specified prefix %s: %s (exit code %s)",
                             cmd, prefix, res.output, res.exit_code)

    pylibdir = txt[len(prefix):]

    # Ubuntu 24.04: the pylibdir has a leading local/, which causes issues later
    # e.g. when symlinking <installdir>/local/* to <installdir>/*
    # we can safely strip this to get a working installation
    local = 'local/'
    if pylibdir.startswith(local):
        log.info("Removing leading /local from determined pylibdir: %s" % pylibdir)
        pylibdir = pylibdir[len(local):]

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

    res = run_shell_cmd("%s -m pip --version" % python_cmd, hidden=True)
    out = res.output

    pip_version_regex = re.compile('^pip ([0-9.]+)')
    res = pip_version_regex.search(out)
    if res:
        pip_version = res.group(1)
        log.info("Found pip version: %s", pip_version)
    else:
        log.warning("Failed to determine pip version from '%s' using pattern '%s'", out, pip_version_regex.pattern)

    return pip_version


def det_py_install_scheme(python_cmd='python'):
    """
    Try to determine active installation scheme used by Python.
    """
    # default installation scheme is 'posix_prefix',
    # see also https://docs.python.org/3/library/sysconfig.html#installation-paths;
    # on Debian/Ubuntu, we may be getting 'posix_local' as custom installation scheme,
    # which injects /local as a subdirectory and cause trouble
    # (see also https://github.com/easybuilders/easybuild-easyblocks/issues/2976)

    log = fancylogger.getLogger('det_py_install_scheme', fname=False)

    # sysconfig._get_default_scheme was renamed to sysconfig.get_default_scheme in Python 3.10
    pyver = det_python_version(python_cmd)
    if LooseVersion(pyver) >= LooseVersion('3.10'):
        get_default_scheme = 'get_default_scheme'
    else:
        get_default_scheme = '_get_default_scheme'

    cmd = "%s -c 'import sysconfig; print(sysconfig.%s())'" % (python_cmd, get_default_scheme)
    log.debug("Determining active Python installation scheme with: %s", cmd)
    res = run_shell_cmd(cmd, hidden=True)
    py_install_scheme = res.output.strip()

    if py_install_scheme in PY_INSTALL_SCHEMES:
        log.info("Active Python installation scheme: %s", py_install_scheme)
    else:
        log.warning("Unknown Python installation scheme: %s", py_install_scheme)

    return py_install_scheme


def handle_local_py_install_scheme(install_dir):
    """
    Handle situation in which 'posix_local' installation scheme was used,
    which implies that <prefix>/local/' rather than <prefix>/ was used as installation prefix...
    """
    # see also https://github.com/easybuilders/easybuild-easyblocks/issues/2976

    log = fancylogger.getLogger('handle_local_py_install_scheme', fname=False)

    install_dir_local = os.path.join(install_dir, 'local')
    if os.path.exists(install_dir_local):
        subdirs = os.listdir(install_dir)
        log.info("Found 'local' subdirectory in installation prefix %s: %s", install_dir, subdirs)

        local_subdirs = os.listdir(install_dir_local)
        log.info("Subdirectories of %s: %s", install_dir_local, local_subdirs)

        # symlink subdirectories of <prefix>/local directly into <prefix>
        cwd = change_dir(install_dir)
        for local_subdir in local_subdirs:
            srcpath = os.path.join('local', local_subdir)
            symlink(srcpath, os.path.join(install_dir, local_subdir), use_abspath_source=False)
        change_dir(cwd)


def symlink_dist_site_packages(install_dir, pylibdirs):
    """
    Symlink site-packages to dist-packages if only the latter is available in the specified directories.
    """
    # in some situations, for example when the default installation scheme is not the upstream default posix_prefix,
    # as is the case in Ubuntu 22.04 (cfr. https://github.com/easybuilders/easybuild-easyblocks/issues/2976),
    # Python packages may get installed in <prefix>/.../dist-packages rather than <prefix>/.../site-packages;
    # we try to determine all possible paths in get_pylibdirs but we still may get it wrong,
    # mostly because distutils.sysconfig.get_python_lib(..., prefix=...) isn't correct when posix_prefix
    # is not the active installation scheme;
    # so taking the coward way out: just symlink site-packages to dist-packages if only latter is available
    dist_pkgs = 'dist-packages'
    for pylibdir in pylibdirs:
        dist_pkgs_path = os.path.join(install_dir, os.path.dirname(pylibdir), dist_pkgs)
        site_pkgs_path = os.path.join(os.path.dirname(dist_pkgs_path), 'site-packages')

        # site-packages may be there as empty directory (see mkdir loop in install_step);
        # just remove it if that's the case so we can symlink to dist-packages
        if os.path.exists(site_pkgs_path) and not os.listdir(site_pkgs_path):
            remove_dir(site_pkgs_path)

        if os.path.exists(dist_pkgs_path) and not os.path.exists(site_pkgs_path):
            symlink(dist_pkgs, site_pkgs_path, use_abspath_source=False)


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
            'download_dep_fail': [True, "Fail if downloaded dependencies are detected", CUSTOM],
            'fix_python_shebang_for': [['bin/*'], "List of files for which Python shebang should be fixed "
                                                  "to '#!/usr/bin/env python' (glob patterns supported) "
                                                  "(default: ['bin/*'])", CUSTOM],
            'install_src': [None, "Source path to pass to the install command (e.g. a whl file)."
                                  "Defaults to '.' for unpacked sources or the first source file specified", CUSTOM],
            'install_target': ['install', "Option to pass to setup.py", CUSTOM],
            'pip_ignore_installed': [True, "Let pip ignore installed Python packages (i.e. don't remove them)", CUSTOM],
            'pip_no_index': [None, "Pass --no-index to pip to disable connecting to PyPi entirely which also disables "
                                   "the pip version check. Enabled by default when pip_ignore_installed=True", CUSTOM],
            'pip_verbose': [None, "Pass --verbose to 'pip install' (if pip is used). "
                                  "Enabled by default if the EB option --debug is used.", CUSTOM],
            'req_py_majver': [None, "Required major Python version (only relevant when using system Python)", CUSTOM],
            'req_py_minver': [None, "Required minor Python version (only relevant when using system Python)", CUSTOM],
            'max_py_majver': [None, "Maximum major Python version (only relevant when using system Python)", CUSTOM],
            'max_py_minver': [None, "Maximum minor Python version (only relevant when using system Python)", CUSTOM],
            'sanity_pip_check': [True, "Run 'python -m pip check' to ensure all required Python packages are "
                                       "installed and check for any package with an invalid (0.0.0) version.", CUSTOM],
            'runtest': [True, "Run unit tests.", CUSTOM],  # overrides default
            'testinstall': [False, "Install into temporary directory prior to running the tests.", CUSTOM],
            'unpack_sources': [None, "Unpack sources prior to build/install. Defaults to 'True' except for whl files",
                               CUSTOM],
            # A version of 0.0.0 is usually an error on installation unless the package does really not provide a
            # version. Those would fail the (extended) sanity_pip_check. So as a last resort they can be added here
            # and will be excluded from that check. Note that the display name is required, i.e. from `pip list`.
            'unversioned_packages': [[], "List of packages that don't have a version at all, i.e. show 0.0.0", CUSTOM],
            'use_pip': [True, "Install using '%s'" % PIP_INSTALL_CMD + " "
                              "Using 'wheel' will create a wheel file with pip during the build step "
                              "which is then installed", CUSTOM],
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
            src_urls[0] = [PYPI_SOURCE]
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

        self.determine_install_command()

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', os.path.join(self.builddir, 'xdg-cache-home'))
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])
        # Users or sites may require using a virtualenv for user installations
        # We need to disable this to be able to install into the modules
        env.setvar('PIP_REQUIRE_VIRTUALENV', 'false')
        # Don't let pip connect to PYPI to check for a new version
        env.setvar('PIP_DISABLE_PIP_VERSION_CHECK', 'true')

        # avoid that lib subdirs are appended to $*LIBRARY_PATH if they don't provide libraries
        # typically, only lib/pythonX.Y/site-packages should be added to $PYTHONPATH (see make_module_extra)
        self.module_load_environment.LD_LIBRARY_PATH.type = ModEnvVarType.PATH_WITH_TOP_FILES
        self.module_load_environment.LIBRARY_PATH.type = ModEnvVarType.PATH_WITH_TOP_FILES

    def determine_install_command(self):
        """
        Determine install command to use.
        """
        self.py_installopts = []
        if self.cfg.get('use_pip', True) or self.cfg.get('use_pip_editable', False):
            self.use_setup_py = False
            self.install_cmd = PIP_INSTALL_CMD
            use_pip_wheel = self.cfg.get('use_pip') == 'wheel'

            pip_verbose = self.cfg.get('pip_verbose', None)
            if pip_verbose or (pip_verbose is None and build_option('debug')):
                self.py_installopts.append('--verbose')
                if use_pip_wheel:
                    self.cfg.update('buildopts', '--verbose')

            # don't auto-install dependencies with pip unless use_pip_for_deps=True
            # the default is use_pip_for_deps=False
            if self.cfg.get('use_pip_for_deps'):
                self.log.info("Using pip to also install the dependencies")
            else:
                self.log.info("Using pip with --no-deps option")
                self.py_installopts.append('--no-deps')
                if use_pip_wheel:
                    self.cfg.update('buildopts', '--no-deps')

            if self.cfg.get('pip_ignore_installed', True):
                # don't (try to) uninstall already availale versions of the package being installed
                self.py_installopts.append('--ignore-installed')

            if self.cfg.get('zipped_egg', False):
                self.py_installopts.append('--egg')

            pip_no_index = self.cfg.get('pip_no_index', None)
            if pip_no_index or (pip_no_index is None and self.cfg.get('download_dep_fail', True)):
                self.py_installopts.append('--no-index')

        else:
            self.use_setup_py = True
            self.install_cmd = SETUP_PY_INSTALL_CMD

            install_target = self.cfg.get_ref('install_target')
            if install_target == EASY_INSTALL_TARGET:
                self.install_cmd += " %(loc)s"
                self.py_installopts.append('--no-deps')
            if self.cfg.get('zipped_egg', False):
                if install_target == EASY_INSTALL_TARGET:
                    self.py_installopts.append('--zip-ok')
                else:
                    raise EasyBuildError("Installing zipped eggs requires using easy_install or pip")

        self.log.info("Using '%s' as install command", self.install_cmd)

    def set_pylibdirs(self):
        """Set Python lib directory-related class variables."""

        self.all_pylibdirs = get_pylibdirs(python_cmd=self.python_cmd)
        self.pylibdir = self.all_pylibdirs[0]

    def prepare_python(self):
        """Python-specific preparations."""

        self.python_cmd = find_python_cmd_from_ec(self.log, self.cfg, self.require_python)

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

    def using_pip_install(self):
        """
        Check whether 'pip install --prefix' is being used to install Python packages.
        """
        if self.install_cmd.startswith(PIP_INSTALL_CMD):
            self.log.debug("Using 'pip install' for installing Python packages: %s" % self.install_cmd)
            return True
        else:
            self.log.debug("Not using 'pip install' for installing Python packages (install command template: %s)",
                           self.install_cmd)
            return False

    def using_local_py_install_scheme(self):
        """
        Determine whether the custom 'posix_local' Python installation scheme is actually used.
        This requires that 'pip install --prefix' is used, since the active Python installation scheme
        doesn't matter when using 'python setup.py install --prefix'.
        """
        # see also  https://github.com/easybuilders/easybuild-easyblocks/issues/2976
        py_install_scheme = det_py_install_scheme(python_cmd=self.python_cmd)
        return py_install_scheme == PY_INSTALL_SCHEME_POSIX_LOCAL and self.using_pip_install()

    def compose_install_command(self, prefix, extrapath=None, installopts=None, preinstallopts=None):
        """Compose full install command."""

        if installopts is None:
            installopts = ' '.join([self.cfg['installopts']] + self.py_installopts)

        if preinstallopts is None:
            preinstallopts = self.cfg['preinstallopts']

        if self.using_pip_install():

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
                    if '--no-build-isolation' not in installopts:
                        installopts += ' --no-build-isolation'

            elif not self.dry_run:
                raise EasyBuildError("Failed to determine pip version!")

        cmd = []
        if extrapath:
            cmd.append(extrapath)

        loc = self.cfg.get('install_src')
        if not loc:
            if self._should_unpack_source() or not self.src:
                # specify current directory
                loc = '.'
            elif isinstance(self.src, str):
                # for extensions, self.src specifies the location of the source file
                loc = self.src
            else:
                # otherwise, self.src is a list of dicts, one element per source file
                loc = self.src[0]['path']

        if self.using_pip_install():
            extras = self.cfg.get('use_pip_extras')
            if extras:
                loc += '[%s]' % extras

        if self.cfg.get('use_pip_editable', False):
            # add --editable option when requested, in the right place (i.e. right before the location specification)
            loc = "--editable %s" % loc

        if self.cfg.get('use_pip_requirement', False):
            # add --requirement option when requested, in the right place (i.e. right before the location specification)
            loc = "--requirement %s" % loc

        cmd.extend([
            preinstallopts,
            self.install_cmd % {
                'installopts': installopts,
                'install_target': self.cfg['install_target'],
                'loc': loc,
                'prefix': prefix,
                'python': self.python_cmd,
            },
        ])

        return ' '.join(cmd)

    def py_post_install_shenanigans(self, install_dir):
        """
        Run post-installation shenanigans on specified installation directory, incl:
        * dealing with 'local' subdirectory in install directory in case 'posix_local' installation scheme was used;
        * symlinking site-packages to dist-packages if only the former is available;
        """
        if self.using_local_py_install_scheme():
            self.log.debug("Looks like the active Python installation scheme injected a 'local' subdirectory...")
            handle_local_py_install_scheme(install_dir)
        else:
            self.log.debug("Looks like active Python installation scheme did not inject a 'local' subdirectory, good!")

        py_install_scheme = det_py_install_scheme(python_cmd=self.python_cmd)
        if py_install_scheme != PY_INSTALL_SCHEME_POSIX_PREFIX:
            symlink_dist_site_packages(install_dir, self.all_pylibdirs)

    def extract_step(self):
        """Unpack source files, unless instructed otherwise."""
        if self._should_unpack_source():
            super(PythonPackage, self).extract_step()

    def pre_install_extension(self):
        """Prepare for installing Python package."""
        super(PythonPackage, self).pre_install_extension()
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
        run_shell_cmd(cmd % {'python': self.python_cmd}, hidden=True)

    def build_step(self):
        """Build Python package using setup.py"""

        # inject extra '%(python)s' template value before getting value of 'buildcmd' custom easyconfig parameter
        self.cfg.template_values['python'] = self.python_cmd
        build_cmd = self.cfg['buildcmd']

        if self.use_setup_py:

            if get_software_root('CMake'):
                include_paths = os.pathsep.join(self.toolchain.get_variable("CPPFLAGS", list))
                library_paths = os.pathsep.join(self.toolchain.get_variable("LDFLAGS", list))
                env.setvar("CMAKE_INCLUDE_PATH", include_paths)
                env.setvar("CMAKE_LIBRARY_PATH", library_paths)

            if not build_cmd:
                build_cmd = 'build'  # Default value for setup.py
            build_cmd = f"{self.python_cmd} setup.py {build_cmd}"

        res = None
        if build_cmd:
            cmd = ' '.join([self.cfg['prebuildopts'], build_cmd, self.cfg['buildopts']])
            res = run_shell_cmd(cmd)
        elif self.cfg.get('use_pip') == 'wheel':
            wheel_dir = tempfile.mkdtemp(prefix=self.name+'_wheel-')
            cmd = self.compose_install_command(
                prefix=wheel_dir,
                preinstallopts=self.cfg['prebuildopts'],
                installopts=self.cfg['buildopts'])
            orig_cmd = cmd
            for src, repl in ((' install ', ' wheel '), (' --prefix=', ' --wheel-dir=')):
                if src not in cmd:
                    raise EasyBuildError("Error adjusting install command `%s` for building wheel: '%s' not found!",
                                         orig_cmd, cmd)
                cmd = cmd.replace(src, repl)
            res = run_shell_cmd(cmd)
            wheels = glob.glob(os.path.join(wheel_dir, '*.whl'))
            if not wheels:
                raise EasyBuildError('Build failed: No wheel files found in %s after running %s', wheel_dir, cmd)
            self.log.info('Build created wheel file(s) ' + ', '.join(wheels))
            # Prepare config values for real installation
            # Source is the wheels
            self.cfg['install_src'] = ' '.join(wheels)
            # Those options no longer apply for installing wheels, unset them to be safe
            for opt in ('use_pip_extras', 'use_pip_requirement'):
                self.cfg[opt] = False

        # keep track of all output, so we can check for auto-downloaded dependencies;
        # take into account that build/install steps may be run multiple times
        # We consider the build and install output together as downloads likely happen here if this is run
        if res:
            self.install_cmd_output += res.output

    def test_step(self, return_output_ec=False):
        """
        Test the built Python package.

        :param return_output: return output and exit code of test command
        """

        if isinstance(self.cfg['runtest'], str):
            self.testcmd = self.cfg['runtest']

        if self.cfg['runtest'] and self.testcmd is not None:
            extrapath = ""
            test_installdir = None

            out, ec = (None, None)

            if self.testinstall:
                # install in test directory and export PYTHONPATH

                try:
                    test_installdir = tempfile.mkdtemp()

                    # if posix_local is the active installation scheme there will be
                    # a 'local' subdirectory in the specified prefix;
                    if self.using_local_py_install_scheme():
                        actual_installdir = os.path.join(test_installdir, 'local')
                    else:
                        actual_installdir = test_installdir
                    # Export the temporary installdir as an environment variable
                    # Some tests (e.g. for astropy) require to be run in the installdir
                    env.setvar('EB_PYTHONPACKAGE_TEST_INSTALLDIR', actual_installdir)

                    self.log.debug("Pre-creating subdirectories in %s: %s", actual_installdir, self.all_pylibdirs)
                    for pylibdir in self.all_pylibdirs:
                        mkdir(os.path.join(actual_installdir, pylibdir), parents=True)
                except OSError as err:
                    raise EasyBuildError("Failed to create test install dir: %s", err)

                # print Python search path (just debugging purposes)
                run_shell_cmd("%s -c 'import sys; print(sys.path)'" % self.python_cmd, hidden=True)

                abs_pylibdirs = [os.path.join(actual_installdir, pylibdir) for pylibdir in self.all_pylibdirs]
                extrapath = "export PYTHONPATH=%s &&" % os.pathsep.join(abs_pylibdirs + ['$PYTHONPATH'])

                cmd = self.compose_install_command(test_installdir, extrapath=extrapath)
                run_shell_cmd(cmd)

                self.py_post_install_shenanigans(test_installdir)

            if self.testcmd:
                testcmd = self.testcmd % {'python': self.python_cmd}
                cmd = ' '.join([
                    extrapath,
                    self.cfg['pretestopts'],
                    testcmd,
                    self.cfg['testopts'],
                ])

                if return_output_ec:
                    res = run_shell_cmd(cmd, fail_on_error=False)
                    # need to retrieve ec by not failing on error
                    (out, ec) = (res.output, res.exit_code)
                    self.log.info("cmd '%s' exited with exit code %s and output:\n%s", cmd, ec, out)
                else:
                    run_shell_cmd(cmd)

            if test_installdir:
                remove_dir(test_installdir)

            if return_output_ec:
                return (out, ec)

    def install_step(self):
        """Install Python package to a custom path using setup.py"""

        # if posix_local is the active installation scheme there will be
        # a 'local' subdirectory in the specified prefix;
        # see also https://github.com/easybuilders/easybuild-easyblocks/issues/2976
        if self.using_local_py_install_scheme():
            actual_installdir = os.path.join(self.installdir, 'local')
        else:
            actual_installdir = self.installdir

        # create expected directories
        abs_pylibdirs = [os.path.join(actual_installdir, pylibdir) for pylibdir in self.all_pylibdirs]
        self.log.debug("Pre-creating subdirectories %s in %s...", abs_pylibdirs, actual_installdir)
        for pylibdir in abs_pylibdirs:
            mkdir(pylibdir, parents=True)

        abs_bindir = os.path.join(actual_installdir, 'bin')

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
        res = run_shell_cmd(cmd)

        # keep track of all output from install command, so we can check for auto-downloaded dependencies;
        # take into account that install step may be run multiple times
        # (for iterated installations over multiply Python versions)
        self.install_cmd_output += res.output

        self.py_post_install_shenanigans(self.installdir)

        # fix shebangs if specified
        self.fix_shebang()

        # restore env vars if it they were set
        for name in ('PYTHONPATH', 'PATH'):
            value = old_values[name]
            if value is not None:
                env.setvar(name, value, verbose=False)

    def install_extension(self, *args, **kwargs):
        """Perform the actual Python package build/installation procedure"""

        # we unpack unless explicitly told otherwise
        kwargs.setdefault('unpack_src', self._should_unpack_source())
        super(PythonPackage, self).install_extension(*args, **kwargs)

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

        if self.cfg.get('download_dep_fail', True):
            self.log.info("Detection of downloaded depdenencies enabled, checking output of installation command...")
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

        if self.cfg.get('sanity_pip_check', True):
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

                    res = run_shell_cmd(pip_check_command, fail_on_error=False)
                    pip_check_msg = res.output
                    if res.exit_code:
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

        # ExtensionEasyBlock handles loading modules correctly for multi_deps, so we clean up fake_mod_data
        # and let ExtensionEasyBlock do its job
        if 'Python' in self.cfg["multi_deps"] and self.fake_mod_data:
            self.clean_up_fake_module(self.fake_mod_data)
            self.sanity_check_module_loaded = False

        parent_success, parent_fail_msg = super(PythonPackage, self).sanity_check_step(*args, **kwargs)

        if parent_fail_msg:
            parent_fail_msg += ', '

        return (parent_success and success, parent_fail_msg + fail_msg)

    def make_module_extra(self, *args, **kwargs):
        """Add install path to PYTHONPATH"""
        txt = ''

        # update $EBPYTHONPREFIXES rather than $PYTHONPATH
        # if this Python package was installed for multiple Python versions, or if we prefer it;
        # note: although EasyBuild framework also has logic for this in EasyBlock.make_module_extra,
        # we retain full control here, since the logic is slightly different
        use_ebpythonprefixes = False
        runtime_deps = [dep['name'] for dep in self.cfg.dependencies(runtime_only=True)]

        if 'Python' in runtime_deps:
            self.log.info("Found Python runtime dependency, so considering $EBPYTHONPREFIXES...")
            if build_option('prefer_python_search_path') == EBPYTHONPREFIXES:
                self.log.info("Preferred Python search path is $EBPYTHONPREFIXES, so using that")
                use_ebpythonprefixes = True

        if self.multi_python or use_ebpythonprefixes:
            path = ''  # EBPYTHONPREFIXES are relative to the install dir
            txt += self.module_generator.prepend_paths(EBPYTHONPREFIXES, path)
        elif self.require_python:
            self.set_pylibdirs()
            for path in self.all_pylibdirs:
                fullpath = os.path.join(self.installdir, path)
                # only extend $PYTHONPATH with existing, non-empty directories
                if os.path.exists(fullpath) and os.listdir(fullpath):
                    txt += self.module_generator.prepend_paths(PYTHONPATH, path)

        return super(PythonPackage, self).make_module_extra(txt, *args, **kwargs)
