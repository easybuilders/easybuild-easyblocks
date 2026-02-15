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
EasyBuild support for building and installing Python, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
"""
import difflib
import glob
import json
import os
import re
import fileinput
import sys
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.base import fancylogger
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.framework.easyconfig.templates import PYPI_SOURCE
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option, ERROR, EBPYTHONPREFIXES
from easybuild.tools.modules import get_software_libdir, get_software_root, get_software_version
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir
from easybuild.tools.filetools import read_file, remove_dir, symlink, write_file
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
from easybuild.tools.utilities import trace_msg
import easybuild.tools.toolchain as toolchain


EXTS_FILTER_PYTHON_PACKAGES = ('python -c "import %(ext_name)s"', "")

# magic value for unlimited stack size
UNLIMITED = 'unlimited'

# Environment variables and values to avoid common issues during Python package installations and usage in EasyBuild
PY_ENV_VARS = {
    # don't add user site directory to sys.path (equivalent to python -s), see https://www.python.org/dev/peps/pep-0370
    'PYTHONNOUSERSITE': '1',
    # Users or sites may require using a virtualenv for user installations
    # We need to disable this to be able to install into modules
    'PIP_REQUIRE_VIRTUALENV': 'false',
    # Don't let pip connect to PYPI to check for a new version
    'PIP_DISABLE_PIP_VERSION_CHECK': 'true',
}

REGEX_PIP_NORMALIZE = re.compile(r"[-_.]+")

# We want the following import order:
# 1. Packages installed into VirtualEnv
# 2. Packages installed into $EBPYTHONPREFIXES (e.g. our modules)
# 3. Packages installed in the Python module
# Note that this script is run after all sys.path manipulation by Python and Virtualenv are done.
# Hence prepending $EBPYTHONPREFIXES would shadow VirtualEnv packages and
# appending would NOT shadow the Python-module packages which makes updating packages via ECs impossible.
# Hence we move all paths which are prefixed with the Python-module path to the back but need to make sure
# not to move the VirtualEnv paths.
SITECUSTOMIZE = """
# sitecustomize.py script installed by EasyBuild,
# to pick up Python packages installed with `--prefix` into folders listed in $%(EBPYTHONPREFIXES)s

import os
import site
import sys

# print debug messages when $%(EBPYTHONPREFIXES)s_DEBUG is defined
debug = os.getenv('%(EBPYTHONPREFIXES)s_DEBUG')

# use prefixes from $EBPYTHONPREFIXES, so they have lower priority than
# virtualenv-installed packages, unlike $PYTHONPATH

ebpythonprefixes = os.getenv('%(EBPYTHONPREFIXES)s')

if ebpythonprefixes:
    postfix = os.path.join('lib', 'python' + '.'.join(map(str, sys.version_info[:2])), 'site-packages')
    if debug:
        print("[%(EBPYTHONPREFIXES)s] postfix subdirectory to consider in installation directories: %%s" %% postfix)

    potential_sys_prefixes = (getattr(sys, attr, None) for attr in ("real_prefix", "base_prefix", "prefix"))
    sys_prefix = next(p for p in potential_sys_prefixes if p)
    base_paths = [p for p in sys.path if p.startswith(sys_prefix)]

    for prefix in ebpythonprefixes.split(os.pathsep):
        if debug:
            print("[%(EBPYTHONPREFIXES)s] prefix: %%s" %% prefix)
        sitedir = os.path.join(prefix, postfix)
        if os.path.isdir(sitedir):
            if debug:
                print("[%(EBPYTHONPREFIXES)s] adding site dir: %%s" %% sitedir)
            site.addsitedir(sitedir)

    # Move base python paths to the end of sys.path so modules can override packages from the core Python module
    sys.path = [p for p in sys.path if p not in base_paths] + base_paths
""" % {'EBPYTHONPREFIXES': EBPYTHONPREFIXES}


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


def det_installed_python_packages(names_only=True, python_cmd=None):
    """
    Return list of Python packages that are installed

    Note that the names are reported by pip and might be different to the name that need to be used to import it.

    :param names_only: boolean indicating whether only names or full info from `pip list` should be returned
    :param python_cmd: Python command to use (if None, 'python' is used)
    """
    log = fancylogger.getLogger('det_installed_python_packages', fname=False)

    if python_cmd is None:
        python_cmd = 'python'

    # Check installed Python packages
    cmd = ' '.join([
        python_cmd, '-m', 'pip',
        'list',
        '--isolated',
        '--disable-pip-version-check',
        '--format', 'json',
    ])
    # only check stdout, not stderr which might contain user facing warnings
    # (on deprecation of Python 2.7, for example)
    res = run_shell_cmd(cmd, split_stderr=True, fail_on_error=False, hidden=True)
    if res.exit_code:
        raise EasyBuildError(f'Failed to determine installed python packages: {res.output}')

    log.info(f'Got list of installed Python packages: {res.output}')
    pkgs = json.loads(res.output.strip())
    return [pkg['name'] for pkg in pkgs] if names_only else pkgs


def run_pip_check(python_cmd=None, **kwargs):
    """
    Check installed Python packages using 'pip check'

    :param unversioned_packages: set of Python packages to exclude in the version existence check
    :param python_cmd: Python command to use (if None, 'python' is used)
    """
    log = fancylogger.getLogger('run_pip_check', fname=False)

    kwargs_keys = kwargs.keys()
    if 'unversioned_packages' in kwargs_keys:
        msg = "Parameter `unversioned_packages` is no longer supported."
        log.deprecated(msg, '6.0')
        kwargs_keys -= {'unversioned_packages'}

    if kwargs_keys:
        raise EasyBuildError(f'Parameter(s) {kwargs_keys} are not allowed.')

    if python_cmd is None:
        python_cmd = 'python'

    pip_check_cmd = f"{python_cmd} -m pip check"

    pip_version = det_pip_version(python_cmd=python_cmd)
    if not pip_version:
        raise EasyBuildError("Failed to determine pip version!")
    min_pip_version = LooseVersion('9.0.0')
    if LooseVersion(pip_version) < min_pip_version:
        raise EasyBuildError(f"pip >= {min_pip_version} is required for '{pip_check_cmd}', found {pip_version}")

    pip_check_errors = []

    res = run_shell_cmd(pip_check_cmd, fail_on_error=False, hidden=True)
    msg = "Check on requirements for installed Python packages with 'pip check': "
    if res.exit_code:
        trace_msg(msg + 'FAIL')
        pip_check_errors.append(f"`{pip_check_cmd}` failed:\n{res.output}")
    else:
        trace_msg(msg + 'OK')
        log.info(f"`{pip_check_cmd}` passed successfully")

    if pip_check_errors:
        raise EasyBuildError('\n'.join(pip_check_errors))


def normalize_pip(name):
    return REGEX_PIP_NORMALIZE.sub("-", name).lower()


def run_pip_list(pkgs, python_cmd=None, unversioned_packages=None):
    """
    Run pip list to verify normalized names and versions of installed Python packages

    :param pkgs: list of package tuples (name, version) as specified in the easyconfig
    """

    log = fancylogger.getLogger('run_pip_list', fname=False)

    if unversioned_packages is None:
        unversioned_packages = set()
    elif isinstance(unversioned_packages, (list, tuple)):
        unversioned_packages = set(unversioned_packages)
    elif not isinstance(unversioned_packages, set):
        raise EasyBuildError("Incorrect value type for 'unversioned_packages' in run_pip_check: %s",
                             type(unversioned_packages))

    if build_option('ignore_pip_unversioned_pkgs'):
        unversioned_packages.update(build_option('ignore_pip_unversioned_pkgs'))

    pip_list_errors = []

    try:
        msg = "Check on installed Python package names and versions with 'pip list': "
        pip_pkgs_dict = det_installed_python_packages(names_only=False, python_cmd=python_cmd)
        trace_msg(msg + 'OK')
        log.info("pip list cmd passed successfully")
    except EasyBuildError as err:
        trace_msg(msg + 'FAIL')
        raise EasyBuildError(f"pip list cmd failed:\n{err}")

    if unversioned_packages:
        normalized_unversioned = {normalize_pip(x) for x in unversioned_packages}
    else:
        normalized_unversioned = set()

    # Create normalized name -> version mapping from the pip list output
    normalized_pip_pkgs = {normalize_pip(x['name']): x['version'] for x in pip_pkgs_dict}

    # Check for packages that likely were not installed correctly (version '0.0.0'), excluding packages that are listed
    # as "unversioned".  This is a common issue caused by using setup.py as the installation method for a package which
    # is released as a generic wheel named name-version-py2.py3-none-any.whl. `tox` creates those from version
    # controlled source code so it will contain a version, but the raw tar.gz does not.
    zero_version = '0.0.0'
    zero_pkg_names = sorted([name for (name, version) in normalized_pip_pkgs.items() if version == zero_version])

    for unversioned_package in sorted(normalized_unversioned):
        try:
            zero_pkg_names.remove(unversioned_package)
            log.debug(f"Excluding unversioned package '{unversioned_package}' from check")
        except ValueError:
            try:
                version = normalized_pip_pkgs[unversioned_package]
            except KeyError:
                msg = f"Package '{unversioned_package}' in unversioned_packages was not found in "
                msg += "the installed packages. Check that the name from `python -m pip list` is used "
                msg += "which may be different than the module name."
            else:
                msg = f"Package '{unversioned_package}' in unversioned_packages has a version of {version} "
                msg += "which is valid. Please remove it from unversioned_packages."
            pip_list_errors.append(msg)

    log.info("Found %s invalid packages out of %s packages", len(zero_pkg_names), len(normalized_pip_pkgs))
    if zero_pkg_names:
        zero_pkg_names_str = '\n'.join(zero_pkg_names)
        msg = "The following Python packages were likely not installed correctly because they show a "
        msg += f"version of '{zero_version}':\n{zero_pkg_names_str}\n"
        msg += "This may be solved by using a *-none-any.whl file as the source instead. "
        msg += "See e.g. the SOURCE*_WHL templates.\n"
        msg += "Otherwise you could check if the package provides a version at all or if e.g. poetry is "
        msg += "required (check the source for a pyproject.toml and see PEP517 for details on that)."
        pip_list_errors.append(msg)

    normalized_pkgs = [(normalize_pip(name), version) for name, version in pkgs]

    missing_names = []
    missing_versions = []

    for name, version in normalized_pkgs:
        # Skip packages in the unversioned list: they have already been checked
        if name in normalized_unversioned:
            continue

        # Skip packages in the zero_pkg_names list: they have already been added to pip_list_errors
        if name in zero_pkg_names:
            continue

        # Check for missing (likely wrong) packages names and propose close matches
        if name not in normalized_pip_pkgs:
            close_matches = difflib.get_close_matches(name, normalized_pip_pkgs.keys())
            missing_names.append(f'{name} (close matches in pip list: {close_matches})')

        # Check for missing (likely wrong) package versions
        elif version != normalized_pip_pkgs[name]:
            missing_versions.append(f'{name} {version} (pip list version: {normalized_pip_pkgs[name]})')

    log.info(f"Found {len(missing_names)} missing names and {len(missing_versions)} missing versions "
             f"out of {len(pkgs)} packages")

    if missing_names:
        missing_names_str = '\n'.join(missing_names)
        msg = "The following Python packages were likely specified with a wrong name because they are missing "
        msg += f"from the 'pip list' output:\n{missing_names_str}"
        pip_list_errors.append(msg)

    if missing_versions:
        missing_versions_str = '\n'.join(missing_versions)
        msg = "The following Python packages were likely specified with a wrong version because they have "
        msg += f"another version in the 'pip list' output:\n{missing_versions_str}"
        pip_list_errors.append(msg)

    if pip_list_errors:
        raise EasyBuildError('\n' + '\n'.join(pip_list_errors))


def set_py_env_vars(log, verbose=False):
    """Set environment variables required/useful for installing or using Python packages"""

    py_vars = PY_ENV_VARS.copy()
    # avoid that pip (ab)uses $HOME/.cache/pip
    # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
    py_vars['XDG_CACHE_HOME'] = os.path.join(tempfile.gettempdir(), 'xdg-cache-home')
    # Only set (all) environment variables if any has a different value to
    # avoid (non)changes (and log messages) for each package in a bundle
    set_required = any(os.environ.get(name, None) != value for name, value in py_vars.items())
    if set_required:
        for name, value in py_vars.items():
            env.setvar(name, value, verbose=verbose)
        log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])


class EB_Python(ConfigureMake):
    """Support for building/installing Python
    - default configure/build_step/make install works fine

    To extend Python by adding extra packages there are two ways:
    - list the packages in the exts_list, this will include the packages in this Python installation
    - create a seperate easyblock, so the packages can be loaded with module load

    e.g., you can include numpy and scipy in a default Python installation
    but also provide newer updated numpy and scipy versions by creating a PythonPackage-derived easyblock for it.
    """

    @staticmethod
    def extra_options():
        """Add extra config options specific to Python."""
        extra_vars = {
            'ebpythonprefixes': [True, "Create sitecustomize.py and allow use of $EBPYTHONPREFIXES", CUSTOM],
            'fix_python_shebang_for': [['bin/*'], "List of files for which Python shebang should be fixed "
                                                  "to '#!/usr/bin/env python' (glob patterns supported) "
                                                  "(default: ['bin/*'])", CUSTOM],
            'install_pip': [True,
                            "Use the ensurepip module (Python 2.7.9+, 3.4+) to install the bundled versions "
                            "of pip and setuptools into Python. You _must_ then use pip for upgrading "
                            "pip & setuptools by installing newer versions as extensions!",
                            CUSTOM],
            'optimized': [True, "Build with expensive, stable optimizations (PGO, etc.) (version >= 3.5.4)", CUSTOM],
            'ulimit_unlimited': [False, "Ensure stack size limit is set to '%s' during build" % UNLIMITED, CUSTOM],
            'use_lto': [None, "Build with Link Time Optimization (>= v3.7.0, potentially unstable on some toolchains). "
                        "If None: auto-detect based on toolchain compiler (version)", CUSTOM],
            'patch_ctypes_ld_library_path': [None,
                                             "The ctypes module strongly relies on LD_LIBRARY_PATH to find "
                                             "libraries. This allows specifying a patch that will only be "
                                             "applied if EasyBuild is configured to filter LD_LIBRARY_PATH, in "
                                             "order to make sure ctypes can still find libraries without it. "
                                             "Please make sure to add the checksum for this patch to 'checksums'.",
                                             CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Constructor for Python easyblock."""
        super().__init__(*args, **kwargs)

        self.pyshortver = '.'.join(self.version.split('.')[:2])

        ext_defaults = {
            # Use PYPI_SOURCE as the default for source_urls of extensions.
            'source_urls': [PYPI_SOURCE],
            # We should enable this (by default) for all extensions because the only installed packages at this point
            # (i.e. those in the site-packages folder) are the default installed ones, e.g. pip & setuptools.
            # And we must upgrade them cleanly, i.e. uninstall them first. This also applies to any other package
            # which is voluntarily or accidentally installed multiple times.
            # Example: Upgrading to a higher version after installing new dependencies.
            'pip_ignore_installed': False,
            # disable per-extension 'pip check', since it's a global check done in sanity check step of Python easyblock
            'sanity_pip_check': False,
            # EasyBuild 5
            'use_pip': True,
        }

        # build and install additional packages with PythonPackage easyblock
        self.cfg['exts_defaultclass'] = "PythonPackage"

        exts_default_options = self.cfg.get_ref('exts_default_options')
        for key, default_value in ext_defaults.items():
            if key not in exts_default_options:
                exts_default_options[key] = default_value
        self.log.debug("exts_default_options: %s", self.cfg['exts_default_options'])

        self.install_pip = self.cfg['install_pip']
        if self.install_pip and not self._has_ensure_pip():
            raise EasyBuildError("The ensurepip module required to install pip (requested by install_pip=True) "
                                 "is not available in Python %s", self.version)

        self._inject_patch_ctypes_ld_library_path()

    def _get_pip_ext_version(self):
        """Return the pip version from exts_list or None"""
        for ext in self.cfg.get_ref('exts_list'):
            # Must be (at least) a name-version tuple
            if isinstance(ext, tuple) and len(ext) >= 2 and ext[0] == 'pip':
                return ext[1]
        return None

    def _inject_patch_ctypes_ld_library_path(self):
        """
        Add patch specified in patch_ctypes_ld_library_path to list of patches if
        EasyBuild is configured to filter $LD_LIBRARY_PATH (and is configured not to filter $LIBRARY_PATH).
        This needs to be done in (or before) the fetch step to ensure that those patches are also fetched.
        """
        # If we filter out $LD_LIBRARY_PATH (not unusual when using rpath), ctypes is not able to dynamically load
        # libraries installed with EasyBuild (see https://github.com/EESSI/software-layer/issues/192).
        # If EasyBuild is configured to filter $LD_LIBRARY_PATH the patch specified in 'patch_ctypes_ld_library_path'
        # are added to the list of patches. Also, we add the checksums_filter_ld_library_path to the checksums list in
        # that case.
        # This mechanism e.g. makes sure we can patch ctypes, which normally strongly relies on $LD_LIBRARY_PATH to find
        # libraries. But, we want to do the patching conditionally on EasyBuild configuration (i.e. which env vars
        # are filtered), hence this setup based on the custom easyconfig parameter 'patch_ctypes_ld_library_path'
        filtered_env_vars = build_option('filter_env_vars') or []
        patch_ctypes_ld_library_path = self.cfg.get('patch_ctypes_ld_library_path')
        if (
            'LD_LIBRARY_PATH' in filtered_env_vars and
            'LIBRARY_PATH' not in filtered_env_vars and
            patch_ctypes_ld_library_path
        ):
            # Some sanity checking so we can raise an early and clear error if needed
            # We expect a (one) checksum for the patch_ctypes_ld_library_path
            checksums = self.cfg['checksums']
            sources = self.cfg['sources']
            patches = self.cfg.get('patches')
            len_patches = len(patches) if patches else 0
            if len_patches + len(sources) + 1 == len(checksums):
                msg = "EasyBuild was configured to filter $LD_LIBRARY_PATH (and not to filter $LIBRARY_PATH). "
                msg += "The ctypes module relies heavily on $LD_LIBRARY_PATH for locating its libraries. "
                msg += "The following patch will be applied to make sure ctypes.CDLL, ctypes.cdll.LoadLibrary "
                msg += f"and ctypes.util.find_library will still work correctly: {patch_ctypes_ld_library_path}."
                self.log.info(msg)
                self.log.info(f"Original list of patches: {self.cfg['patches']}")
                self.log.info(f"Patch to be added: {patch_ctypes_ld_library_path}")
                self.cfg.update('patches', [patch_ctypes_ld_library_path])
                self.log.info(f"Updated list of patches: {self.cfg['patches']}")
            else:
                msg = "The length of 'checksums' (%s) is not equal to the total amount of sources (%s) + patches (%s). "
                msg += "Did you forget to add a checksum for patch_ctypes_ld_library_path?"
                raise EasyBuildError(msg, len(checksums), len(sources), len_patches + 1)
        # If LD_LIBRARY_PATH is filtered, but no patch is specified, warn the user that his may not work
        elif (
            'LD_LIBRARY_PATH' in filtered_env_vars and
            'LIBRARY_PATH' not in filtered_env_vars and
            not patch_ctypes_ld_library_path
        ):
            msg = "EasyBuild was configured to filter $LD_LIBRARY_PATH (and not to filter $LIBRARY_PATH). "
            msg += "However, no patch for ctypes was specified through 'patch_ctypes_ld_library_path' in the "
            msg += "easyconfig. Note that ctypes.util.find_library, ctypes.CDLL and ctypes.cdll.LoadLibrary heavily "
            msg += "rely on $LD_LIBRARY_PATH. Without the patch, a setup without $LD_LIBRARY_PATH will likely not work "
            msg += "correctly."
            self.log.warning(msg)

    def patch_step(self, *args, **kwargs):
        """
        Custom patch step for Python:
        * patch setup.py when --sysroot EasyBuild configuration setting is used
        """

        super().patch_step(*args, **kwargs)

        if self.install_pip:
            # Ignore user site dir. -E ignores PYTHONNOUSERSITE, so we have to add -s
            apply_regex_substitutions('configure', [(r"(PYTHON_FOR_BUILD=.*-E)'", r"\1 -s'")])

        # if we're installing Python with an alternate sysroot,
        # we need to patch setup.py which includes hardcoded paths like /usr/include and /lib64;
        # this fixes problems like not being able to build the _ssl module ("Could not build the ssl module")
        # Python 3.12 doesn't have setup.py any more
        sysroot = build_option('sysroot')
        if sysroot and LooseVersion(self.version) < LooseVersion('3.12'):
            sysroot_inc_dirs, sysroot_lib_dirs = [], []

            for pattern in ['include*', os.path.join('usr', 'include*')]:
                sysroot_inc_dirs.extend(glob.glob(os.path.join(sysroot, pattern)))

            if sysroot_inc_dirs:
                sysroot_inc_dirs = ', '.join(["'%s'" % x for x in sysroot_inc_dirs])
            else:
                raise EasyBuildError("No include directories found in sysroot %s!", sysroot)

            for pattern in ['lib*', os.path.join('usr', 'lib*')]:
                sysroot_lib_dirs.extend(glob.glob(os.path.join(sysroot, pattern)))

            if sysroot_lib_dirs:
                sysroot_lib_dirs = ', '.join(["'%s'" % x for x in sysroot_lib_dirs])
            else:
                raise EasyBuildError("No lib directories found in sysroot %s!", sysroot)

            setup_py_fn = 'setup.py'
            setup_py_txt = read_file(setup_py_fn)

            # newer Python versions (3.6+) have refactored code, requires different patching approach
            if "system_include_dirs = " in setup_py_txt:
                regex_subs = [
                    (r"(system_include_dirs = \[).*\]", r"\1%s]" % sysroot_inc_dirs),
                    (r"(system_lib_dirs = \[).*\]", r"\1%s]" % sysroot_lib_dirs),
                ]
            else:
                regex_subs = [
                    (r"^([ ]+)'/usr/include',", r"\1%s," % sysroot_inc_dirs),
                    (r"\['/usr/include'\]", r"[%s]" % sysroot_inc_dirs),
                    (r"^([ ]+)'/lib64', '/usr/lib64',", r"\1%s," % sysroot_lib_dirs),
                    (r"^[ ]+'/lib', '/usr/lib',", ''),
                ]

            # Replace remaining hardcoded paths like '/usr/include', '/usr/lib' or '/usr/local',
            # where these paths are appearing inside single quotes (').
            # Inject sysroot in front to avoid picking up anything outside of sysroot,
            # We can leverage the single quotes such that we do not accidentally fiddle with other entries,
            # like /prefix/usr/include .
            for usr_subdir in ('usr/include', 'usr/lib', 'usr/local'):
                sysroot_usr_subdir = os.path.join(sysroot, usr_subdir)
                regex_subs.append((r"'/%s" % usr_subdir, r"'%s" % sysroot_usr_subdir))
                regex_subs.append((r'"/%s' % usr_subdir, r'"%s' % sysroot_usr_subdir))

            apply_regex_substitutions(setup_py_fn, regex_subs)

        # The path to ldconfig is hardcoded in cpython.util._findSoname_ldconfig(name) as /sbin/ldconfig.
        # This is incorrect if a custom sysroot is used
        # Have confirmed for all versions starting with this one that _findSoname_ldconfig hardcodes /sbin/ldconfig
        if sysroot is not None and LooseVersion(self.version) >= "3.9.1":
            orig_ld_config_call = "with subprocess.Popen(['/sbin/ldconfig', '-p'],"
            ctypes_util_py = os.path.join("Lib", "ctypes", "util.py")
            orig_ld_config_call_regex = r'(\s*)' + re.escape(orig_ld_config_call) + r'(\s*)'
            updated_ld_config_call = "with subprocess.Popen(['%s/sbin/ldconfig', '-p']," % sysroot
            apply_regex_substitutions(
                ctypes_util_py,
                [(orig_ld_config_call_regex, r'\1' + updated_ld_config_call + r'\2')],
                on_missing_match=ERROR
            )

    def prepare_for_extensions(self):
        """
        Set default class and filter for Python packages
        """
        self.cfg['exts_filter'] = EXTS_FILTER_PYTHON_PACKAGES

        # don't pass down any build/install options that may have been specified
        # 'make' options do not make sense for when building/installing Python libraries (usually via 'python setup.py')
        msg = "Unsetting '%s' easyconfig parameter before building/installing extensions: %s"
        for param in ['buildopts', 'installopts']:
            if self.cfg[param]:
                self.log.debug(msg, param, self.cfg[param])
            self.cfg[param] = ''

        if self.install_pip:
            # When using ensurepip, then pip must be used to upgrade pip and setuptools
            # Otherwise it will only copy new files leading to a combination of files from the old and new version
            use_pip_default = self.cfg['exts_default_options'].get('use_pip')
            # self.exts is populated in fetch_step
            for ext in self.exts:
                if ext['name'] in ('pip', 'setuptools') and not ext.get('options', {}).get('use_pip', use_pip_default):
                    raise EasyBuildError("When using ensurepip to install pip (requested by install_pip=True) "
                                         "you must set 'use_pip=True' for the pip & setuptools extensions. "
                                         "Found 'use_pip=False' (maybe by default) for %s.",
                                         ext['name'])

    def auto_detect_lto_support(self):
        """Return True, if LTO should be enabled for current toolchain"""
        result = False
        # GCC >= 8 should be stable enough for LTO
        if self.toolchain.comp_family() == toolchain.GCC:
            gcc_ver = get_software_version('GCCcore') or get_software_version('GCC')
            if gcc_ver and LooseVersion(gcc_ver) >= LooseVersion('8.0'):
                self.log.info("Auto-enabling LTO since GCC >= v8.0 is used as toolchain compiler")
                result = True
        return result

    def _has_ensure_pip(self):
        """Check if  this Python version has/should have the ensurepip package"""
        # Pip is included since 3.4 via ensurepip https://docs.python.org/3.4/whatsnew/changelog.html
        # And in 2.7.9+: https://docs.python.org/2.7/whatsnew/2.7.html#pep-477-backport-ensurepip-pep-453-to-python-2-7
        version = LooseVersion(self.version)
        return version >= LooseVersion('3.4.0') or (version < LooseVersion('3') and version >= LooseVersion('2.7.9'))

    def configure_step(self):
        """Set extra configure options."""
        # Check for and report distutils user configs which may make the installation fail
        # See https://github.com/easybuilders/easybuild-easyconfigs/issues/11009
        for cfg in [os.path.join(os.path.expanduser('~'), name) for name in ('.pydistutils.cfg', 'pydistutils.cfg')]:
            if os.path.exists(cfg):
                raise EasyBuildError("Legacy distutils user configuration file found at %s. Aborting.", cfg)

        self.cfg.update('configopts', "--enable-shared")

        # Explicitely enable thread support on < 3.7 (always on 3.7+)
        if LooseVersion(self.version) < LooseVersion('3.7'):
            self.cfg.update('configopts', "--with-threads")

        # Explicitely enable unicode on Python 2, always on for Python 3
        # Need to be careful to match the unicode settings to the underlying python
        if LooseVersion(self.version) < LooseVersion('3.0'):
            if sys.maxunicode == 1114111:
                self.cfg.update('configopts', "--enable-unicode=ucs4")
            elif sys.maxunicode == 65535:
                self.cfg.update('configopts', "--enable-unicode=ucs2")
            else:
                raise EasyBuildError("Unknown maxunicode value for your python: %d" % sys.maxunicode)

        # LTO introduced in 3.7.0
        if LooseVersion(self.version) >= LooseVersion('3.7.0'):
            use_lto = self.cfg['use_lto']
            if use_lto is None:
                use_lto = self.auto_detect_lto_support()
            if use_lto:
                self.cfg.update('configopts', "--with-lto")

        # Enable further optimizations at the cost of a longer build
        # Introduced in 3.5.3, fixed in 3.5.4: https://docs.python.org/3.5/whatsnew/changelog.html
        if self.cfg['optimized'] and LooseVersion(self.version) >= LooseVersion('3.5.4'):
            # only configure with --enable-optimizations when compiling Python with (recent) GCC compiler
            if self.toolchain.comp_family() == toolchain.GCC:
                gcc_ver = get_software_version('GCCcore') or get_software_version('GCC')
                if LooseVersion(gcc_ver) >= LooseVersion('8.0'):
                    self.cfg.update('configopts', "--enable-optimizations")

        # When ensurepip is available we explicitely set this.
        # E.g. in 3.4 it is by default "upgrade", i.e. on which is unexpected when we did set it to off
        if self._has_ensure_pip():
            self.cfg.update('configopts', "--with-ensurepip=" + ('no', 'upgrade')[self.install_pip])

        modules_setup = os.path.join(self.cfg['start_dir'], 'Modules', 'Setup')
        if LooseVersion(self.version) < LooseVersion('3.8.0'):
            modules_setup += '.dist'

        libreadline = get_software_root('libreadline')
        if libreadline:
            ncurses = get_software_root('ncurses')
            if ncurses:
                readline_libdir = get_software_libdir('libreadline')
                ncurses_libdir = get_software_libdir('ncurses')
                readline_static_lib = os.path.join(libreadline, readline_libdir, 'libreadline.a')
                ncurses_static_lib = os.path.join(ncurses, ncurses_libdir, 'libncurses.a')
                readline = "readline readline.c %s %s" % (readline_static_lib, ncurses_static_lib)
                for line in fileinput.input(modules_setup, inplace='1', backup='.readline'):
                    line = re.sub(r"^#readline readline.c.*", readline, line)
                    sys.stdout.write(line)
            else:
                raise EasyBuildError("Both libreadline and ncurses are required to ensure readline support")

        openssl = get_software_root('OpenSSL')
        if openssl:
            for line in fileinput.input(modules_setup, inplace='1', backup='.ssl'):
                line = re.sub(r"^#SSL=.*", "SSL=%s" % openssl, line)
                line = re.sub(r"^#(\s*-DUSE_SSL -I)", r"\1", line)
                line = re.sub(r"^#(\s*-L\$\(SSL\)/lib )", r"\1 -L$(SSL)/lib64 ", line)
                sys.stdout.write(line)

        tcl = get_software_root('Tcl')
        tk = get_software_root('Tk')
        if tcl and tk:
            tclver = get_software_version('Tcl')
            tkver = get_software_version('Tk')
            tcltk_maj_min_ver = '.'.join(tclver.split('.')[:2])
            tcltk_maj_ver = tkver.split('.')[0]
            if tcltk_maj_min_ver != '.'.join(tkver.split('.')[:2]):
                raise EasyBuildError("Tcl and Tk major/minor versions don't match: %s vs %s", tclver, tkver)

            tcl_libdir = os.path.join(tcl, get_software_libdir('Tcl'))
            tk_libdir = os.path.join(tk, get_software_libdir('Tk'))
            if LooseVersion(tkver) > '9.0':
                tk_libname = f'tcl{tcltk_maj_ver}tk{tcltk_maj_min_ver}'
            else:
                tk_libname = f'tk{tcltk_maj_min_ver}'
            tcltk_libs = f"-L%(tcl_libdir)s -L%(tk_libdir)s -ltcl%(maj_min_ver)s -l{tk_libname}" % {
                'tcl_libdir': tcl_libdir,
                'tk_libdir': tk_libdir,
                'maj_min_ver': tcltk_maj_min_ver,
            }
            # Determine if we need to pass -DTCL_WITH_EXTERNAL_TOMMATH
            # by checking if libtommath has a software root. If we don't,
            # loading Tkinter will fail, causing the module to be deleted
            # before installation. This would typically be handled by
            # pkg-config.
            libtommath = get_software_root('libtommath')
            libtommath_define = ''
            if libtommath:
                libtommath_define += '-DTCL_WITH_EXTERNAL_TOMMATH'

            if LooseVersion(self.version) < '3.11':
                self.cfg.update('configopts',
                                "--with-tcltk-includes='-I%s/include -I%s/include %s'" % (tcl, tk, libtommath_define))
                self.cfg.update('configopts', "--with-tcltk-libs='%s'" % tcltk_libs)
            else:
                env.setvar('TCLTK_CFLAGS', '-I%s/include -I%s/include %s' % (tcl, tk, libtommath_define))
                env.setvar('TCLTK_LIBS', tcltk_libs)

        # This matters e.g. when python installs the bundled pip & setuptools (for >= 3.4)
        set_py_env_vars(self.log)

        super().configure_step()

    def build_step(self, *args, **kwargs):
        """Custom build procedure for Python, ensure stack size limit is set to 'unlimited' (if desired)."""

        # make sure installation directory doesn't already exist when building with --rpath and
        # configuring with --enable-optimizations, since that leads to errors like:
        #   ./python: symbol lookup error: ./python: undefined symbol: __gcov_indirect_call
        # see also https://bugs.python.org/issue29712
        enable_opts_flag = '--enable-optimizations'
        if build_option('rpath') and enable_opts_flag in self.cfg['configopts'] and os.path.exists(self.installdir):
            warning_msg = "Removing existing installation directory '%s', "
            warning_msg += "because EasyBuild is configured to use RPATH linking "
            warning_msg += "and %s configure option is used." % enable_opts_flag
            print_warning(warning_msg % self.installdir)
            remove_dir(self.installdir)

        if self.cfg['ulimit_unlimited']:
            # determine current stack size limit
            res = run_shell_cmd("ulimit -s")
            curr_ulimit_s = res.output.strip()

            # figure out hard limit for stack size limit;
            # this determines whether or not we can use "ulimit -s unlimited"
            res = run_shell_cmd("ulimit -s -H")
            max_ulimit_s = res.output.strip()

            if curr_ulimit_s == UNLIMITED:
                self.log.info("Current stack size limit is %s: OK", curr_ulimit_s)
            elif max_ulimit_s == UNLIMITED:
                self.log.info("Current stack size limit is %s, setting it to %s for build...",
                              curr_ulimit_s, UNLIMITED)
                self.cfg.update('prebuildopts', "ulimit -s %s && " % UNLIMITED)
            else:
                msg = "Current stack size limit is %s, and can not be set to %s due to hard limit of %s;"
                msg += " setting stack size limit to %s instead, "
                msg += " this may break part of the compilation (e.g. hashlib)..."
                print_warning(msg % (curr_ulimit_s, UNLIMITED, max_ulimit_s, max_ulimit_s))
                self.cfg.update('prebuildopts', "ulimit -s %s && " % max_ulimit_s)

        super().build_step(*args, **kwargs)

    @property
    def site_packages_path(self):
        return os.path.join('lib', 'python' + self.pyshortver, 'site-packages')

    def install_step(self):
        """Extend make install to make sure that the 'python' command is present."""

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        super().install_step()

        # Create non-versioned, relative symlinks for python, python-config and pip
        python_binary_path = os.path.join(self.installdir, 'bin', 'python')
        if not os.path.isfile(python_binary_path):
            symlink('python' + self.pyshortver, python_binary_path, use_abspath_source=False)
        python_config_binary_path = os.path.join(self.installdir, 'bin', 'python-config')
        if not os.path.isfile(python_config_binary_path):
            symlink('python' + self.pyshortver + '-config', python_config_binary_path, use_abspath_source=False)
        if self.install_pip:
            pip_binary_path = os.path.join(self.installdir, 'bin', 'pip')
            if not os.path.isfile(pip_binary_path):
                symlink('pip' + self.pyshortver, pip_binary_path, use_abspath_source=False)

        if self.cfg.get('ebpythonprefixes'):
            write_file(os.path.join(self.installdir, self.site_packages_path, 'sitecustomize.py'), SITECUSTOMIZE)

        # symlink lib/python*/lib-dynload to lib64/python*/lib-dynload if it doesn't exist;
        # see https://github.com/easybuilders/easybuild-easyblocks/issues/1957
        lib_dynload = 'lib-dynload'
        python_lib_dynload = os.path.join('python%s' % self.pyshortver, lib_dynload)
        lib_dynload_path = os.path.join(self.installdir, 'lib', python_lib_dynload)
        if not os.path.exists(lib_dynload_path):
            lib64_dynload_path = os.path.join('lib64', python_lib_dynload)
            if os.path.exists(os.path.join(self.installdir, lib64_dynload_path)):
                lib_dynload_parent = os.path.dirname(lib_dynload_path)
                mkdir(lib_dynload_parent, parents=True)
                cwd = change_dir(lib_dynload_parent)
                # use relative path as target, to avoid hardcoding path to install directory
                target_lib_dynload = os.path.join('..', '..', lib64_dynload_path)
                symlink(target_lib_dynload, lib_dynload)
                change_dir(cwd)

    def _sanity_check_ctypes_ld_library_path_patch(self):
        """
        Check that ctypes.util.find_library and ctypes.CDLL work as expected.
        When $LD_LIBRARY_PATH is filtered, a patch is required for this to work correctly
        (see patch_ctypes_ld_library_path).
        """
        # Try find_library first, since ctypes.CDLL relies on that to work correctly
        cmd = "python -c 'from ctypes import util; print(util.find_library(\"libpython3.so\"))'"
        res = run_shell_cmd(cmd)
        out = res.output.strip()
        escaped_python_root = re.escape(self.installdir)
        pattern = rf"^{escaped_python_root}.*libpython3\.so$"
        match = re.match(pattern, out)
        self.log.debug(f"Matching regular expression pattern {pattern} to string {out}")
        if match:
            msg = "Call to ctypes.util.find_library('libpython3.so') successfully found libpython3.so under "
            msg += f"the installation prefix of the current Python installation ({self.installdir}). "
            if self.cfg.get('patch_ctypes_ld_library_path'):
                msg += "This indicates that the patch that fixes ctypes when EasyBuild is "
                msg += "configured to filter $LD_LIBRARY_PATH was applied succesfully."
            self.log.info(msg)
        else:
            msg = "Finding the library libpython3.so using ctypes.util.find_library('libpython3.so') failed. "
            msg += "The ctypes Python module requires a patch when EasyBuild is configured to filter $LD_LIBRARY_PATH. "
            msg += "Please check if you specified a patch through patch_ctypes_ld_library_path and check "
            msg += "the logs to see if it applied correctly."
            raise EasyBuildError(msg)
        # Now that we know find_library was patched correctly, check if ctypes.CDLL is also patched correctly
        cmd = "python -c 'import ctypes; print(ctypes.CDLL(\"libpython3.so\"))'"
        res = run_shell_cmd(cmd)
        out = res.output.strip()
        pattern = rf"^<CDLL '{escaped_python_root}.*libpython3\.so', handle [a-f0-9]+ at 0x[a-f0-9]+>$"
        match = re.match(pattern, out)
        self.log.debug(f"Matching regular expression pattern {pattern} to string {out}")
        if match:
            msg = "Call to ctypes.CDLL('libpython3.so') succesfully opened libpython3.so. "
            if self.cfg.get('patch_ctypes_ld_library_path'):
                msg += "This indicates that the patch that fixes ctypes when $LD_LIBRARY_PATH is not set "
                msg += "was applied successfully."
            self.log.info(msg)
            msg = "Call to ctypes.CDLL('libpython3.so') succesfully opened libpython3.so. "
            if self.cfg.get('patch_ctypes_ld_library_path'):
                msg += "This indicates that the patch that fixes ctypes when $LD_LIBRARY_PATH is not set "
                msg += "was applied successfully."
        else:
            msg = "Opening of libpython3.so using ctypes.CDLL('libpython3.so') failed. "
            msg += "The ctypes Python module requires a patch when EasyBuild is configured to filter $LD_LIBRARY_PATH. "
            msg += "Please check if you specified a patch through patch_ctypes_ld_library_path and check "
            msg += "the logs to see if it applied correctly."
            raise EasyBuildError(msg)

    def _sanity_check_ebpythonprefixes(self):
        """Check that EBPYTHONPREFIXES works"""
        temp_prefix = tempfile.mkdtemp(suffix='-tmp-prefix')
        temp_site_packages_path = os.path.join(temp_prefix, self.site_packages_path)
        mkdir(temp_site_packages_path, parents=True)  # Must exist
        res = run_shell_cmd("%s=%s python -c 'import sys; print(sys.path)'" % (EBPYTHONPREFIXES, temp_prefix))
        out = res.output.strip()
        # Output should be a list which we can evaluate directly
        if not out.startswith('[') or not out.endswith(']'):
            raise EasyBuildError("Unexpected output for sys.path: %s", out)
        paths = eval(out)
        base_site_packages_path = os.path.join(self.installdir, self.site_packages_path)
        try:
            base_prefix_idx = paths.index(base_site_packages_path)
        except ValueError:
            raise EasyBuildError("The Python install path (%s) was not added to sys.path (%s)",
                                 base_site_packages_path, paths)
        try:
            eb_prefix_idx = paths.index(temp_site_packages_path)
        except ValueError:
            raise EasyBuildError("EasyBuilds sitecustomize.py did not add %s to sys.path (%s)",
                                 temp_site_packages_path, paths)
        if eb_prefix_idx > base_prefix_idx:
            raise EasyBuildError("EasyBuilds sitecustomize.py did not add %s before %s to sys.path (%s)",
                                 temp_site_packages_path, base_site_packages_path, paths)

    def load_module(self, *args, **kwargs):
        """(Re)set environment variables after loading module file.

        Required here to ensure the variables are also defined for stand-alone installations,
        because the environment is reset to the initial environment right before loading the module.
        """

        super().load_module(*args, **kwargs)
        set_py_env_vars(self.log)

    def sanity_check_step(self):
        """Custom sanity check for Python."""

        shlib_ext = get_shared_lib_ext()

        try:
            fake_mod_data = self.load_fake_module()
        except EasyBuildError as err:
            raise EasyBuildError("Loading fake module failed: %s", err)

        # Set after loading module
        set_py_env_vars(self.log)

        # global 'pip check' to verify that version requirements are met for Python packages installed as extensions
        run_pip_check(python_cmd='python')

        exts_list = self.cfg.get_ref('exts_list')
        if exts_list and not self.ext_instances:
            # populate self.ext_instances if not done yet (e.g. with --sanity-check-only or --rebuild --module-only)
            self.init_ext_instances()

        pkgs = [(x.name, x.version) for x in self.ext_instances]
        run_pip_list(pkgs, python_cmd='python')

        abiflags = ''
        if LooseVersion(self.version) >= LooseVersion("3"):
            run_shell_cmd("command -v python", hidden=True)
            cmd = 'python -c "import sysconfig; print(sysconfig.get_config_var(\'abiflags\'));"'
            res = run_shell_cmd(cmd, hidden=True)
            abiflags = res.output
            if not abiflags:
                raise EasyBuildError("Failed to determine abiflags: %s", abiflags)
            else:
                abiflags = abiflags.strip()

        # make sure hashlib is installed correctly, there should be no errors/output when 'import hashlib' is run
        # (python will exit with 0 regardless of whether or not errors are printed...)
        # cfr. https://github.com/easybuilders/easybuild-easyconfigs/issues/6484
        cmd = "python -c 'import hashlib'"
        res = run_shell_cmd(cmd)
        out = res.output
        regex = re.compile('error', re.I)
        if regex.search(out):
            raise EasyBuildError("Found one or more errors in output of %s: %s", cmd, out)
        else:
            self.log.info("No errors found in output of %s: %s", cmd, out)

        if self.cfg.get('ebpythonprefixes'):
            self._sanity_check_ebpythonprefixes()

        # If the conditions for applying the patch specified through patch_ctypes_ld_library_path are met,
        # check that a patch was applied and indeed fixed the issue
        filtered_env_vars = build_option('filter_env_vars') or []
        if 'LD_LIBRARY_PATH' in filtered_env_vars and 'LIBRARY_PATH' not in filtered_env_vars:
            self._sanity_check_ctypes_ld_library_path_patch()

        pyver = 'python' + self.pyshortver
        custom_paths = {
            'files': [
                os.path.join('bin', pyver),
                os.path.join('bin', 'python'),
                os.path.join('bin', pyver + '-config'),
                os.path.join('bin', 'python-config'),
                os.path.join('lib', 'lib' + pyver + abiflags + '.' + shlib_ext),
            ],
            'dirs': [os.path.join('include', pyver + abiflags), os.path.join('lib', pyver, 'lib-dynload')],
        }

        # cleanup
        self.clean_up_fake_module(fake_mod_data)

        custom_commands = [
            "python --version",
            "python-config --help",  # make sure that symlink was created correctly
            "python -c 'import _ctypes'",  # make sure that foreign function interface (libffi) works
            "python -c 'import _ssl'",  # make sure SSL support is enabled one way or another
            "python -c 'import readline'",  # make sure readline support was built correctly
        ]

        if self.install_pip:
            # Check that pip and setuptools are installed
            py_maj_version = self.version.split('.')[0]
            custom_paths['files'].extend([
                os.path.join('bin', pip) for pip in ('pip', 'pip' + py_maj_version, 'pip' + self.pyshortver)
            ])
            custom_commands.extend([
                "python -c 'import pip'",
                "python -c 'import setuptools'",
            ])

        if get_software_root('Tk'):
            # also check whether importing tkinter module works, name is different for Python v2.x and v3.x
            if LooseVersion(self.version) >= LooseVersion('3'):
                tkinter = 'tkinter'
            else:
                tkinter = 'Tkinter'
            custom_commands.append("python -c 'import %s'" % tkinter)

            # check whether _tkinter*.so is found, exact filename doesn't matter
            tkinter_so = os.path.join(self.installdir, 'lib', pyver, 'lib-dynload', '_tkinter*.' + shlib_ext)
            tkinter_so_hits = glob.glob(tkinter_so)
            if len(tkinter_so_hits) == 1:
                self.log.info("Found exactly one _tkinter*.so: %s", tkinter_so_hits[0])
            else:
                raise EasyBuildError("Expected to find exactly one _tkinter*.so: %s", tkinter_so_hits)

        super().sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
