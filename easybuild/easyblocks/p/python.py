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
import glob
import os
import re
import fileinput
import sys
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
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
import easybuild.tools.toolchain as toolchain


EXTS_FILTER_PYTHON_PACKAGES = ('python -s -c "import %(ext_name)s"', "")

# magic value for unlimited stack size
UNLIMITED = 'unlimited'

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
            'install_pip': [True,
                            "Use the ensurepip module (Python 2.7.9+, 3.4+) to install the bundled versions "
                            "of pip and setuptools into Python. You _must_ then use pip for upgrading "
                            "pip & setuptools by installing newer versions as extensions!",
                            CUSTOM],
            'optimized': [True, "Build with expensive, stable optimizations (PGO, etc.) (version >= 3.5.4)", CUSTOM],
            'ulimit_unlimited': [False, "Ensure stack size limit is set to '%s' during build" % UNLIMITED, CUSTOM],
            'use_lto': [None, "Build with Link Time Optimization (>= v3.7.0, potentially unstable on some toolchains). "
                        "If None: auto-detect based on toolchain compiler (version)", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """Constructor for Python easyblock."""
        super(EB_Python, self).__init__(*args, **kwargs)

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
            # Python installations must be clean. Requires pip >= 9
            'sanity_pip_check': LooseVersion(self._get_pip_ext_version() or '0.0') >= LooseVersion('9.0'),
            # EasyBuild 5
            'use_pip': True,
        }

        exts_default_options = self.cfg.get_ref('exts_default_options')
        for key in ext_defaults:
            if key not in exts_default_options:
                exts_default_options[key] = ext_defaults[key]
        self.log.debug("exts_default_options: %s", self.cfg['exts_default_options'])

        self.install_pip = self.cfg['install_pip']
        if self.install_pip:
            if not self._has_ensure_pip():
                raise EasyBuildError("The ensurepip module required to install pip (requested by install_pip=True) "
                                     "is not available in Python %s", self.version)

    def _get_pip_ext_version(self):
        """Return the pip version from exts_list or None"""
        for ext in self.cfg.get_ref('exts_list'):
            # Must be (at least) a name-version tuple
            if isinstance(ext, tuple) and len(ext) >= 2 and ext[0] == 'pip':
                return ext[1]
        return None

    def patch_step(self, *args, **kwargs):
        """
        Custom patch step for Python:
        * patch setup.py when --sysroot EasyBuild configuration setting is used
        """

        super(EB_Python, self).patch_step(*args, **kwargs)

        if self.install_pip:
            # Ignore user site dir. -E ignores PYTHONNOUSERSITE, so we have to add -s
            apply_regex_substitutions('configure', [(r"(PYTHON_FOR_BUILD=.*-E)'", r"\1 -s'")])

        # If we filter out LD_LIBRARY_PATH (not unusual when using rpath), ctypes is not able to dynamically load
        # libraries installed with EasyBuild (see https://github.com/EESSI/software-layer/issues/192).
        # ctypes is using GCC (and therefore LIBRARY_PATH) to figure out the full location but then only returns the
        # soname, instead let's return the full path in this particular scenario
        filtered_env_vars = build_option('filter_env_vars') or []
        if 'LD_LIBRARY_PATH' in filtered_env_vars and 'LIBRARY_PATH' not in filtered_env_vars:
            ctypes_util_py = os.path.join("Lib", "ctypes", "util.py")
            orig_gcc_so_name = None
            # Let's do this incrementally since we are going back in time
            if LooseVersion(self.version) >= "3.9.1":
                # From 3.9.1 to at least v3.12.4 there is only one match for this line
                orig_gcc_so_name = "_get_soname(_findLib_gcc(name)) or _get_soname(_findLib_ld(name))"
            if orig_gcc_so_name:
                orig_gcc_so_name_regex = r'(\s*)' + re.escape(orig_gcc_so_name) + r'(\s*)'
                # _get_soname() takes the full path as an argument and uses objdump to get the SONAME field from
                # the shared object file. The presence or absence of the SONAME field in the ELF header of a shared
                # library is influenced by how the library is compiled and linked. For manually built libraries we
                # may be lacking this field, this approach also solves that problem.
                updated_gcc_so_name = (
                    "_findLib_gcc(name) or _findLib_ld(name)"
                )
                apply_regex_substitutions(
                    ctypes_util_py,
                    [(orig_gcc_so_name_regex, r'\1' + updated_gcc_so_name + r'\2')],
                    on_missing_match=ERROR
                )

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
        if sysroot is not None:
            # Have confirmed for all versions starting with this one that _findSoname_ldconfig hardcodes /sbin/ldconfig
            if LooseVersion(self.version) >= "3.9.1":
                orig_ld_config_call = "with subprocess.Popen(['/sbin/ldconfig', '-p'],"
            if orig_ld_config_call:
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
        # build and install additional packages with PythonPackage easyblock
        self.cfg['exts_defaultclass'] = "PythonPackage"
        self.cfg['exts_filter'] = EXTS_FILTER_PYTHON_PACKAGES

        # don't add user site directory to sys.path (equivalent to python -s)
        env.setvar('PYTHONNOUSERSITE', '1')

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
                if ext['name'] in ('pip', 'setuptools'):
                    if not ext.get('options', {}).get('use_pip', use_pip_default):
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
            if tcltk_maj_min_ver != '.'.join(tkver.split('.')[:2]):
                raise EasyBuildError("Tcl and Tk major/minor versions don't match: %s vs %s", tclver, tkver)

            tcl_libdir = os.path.join(tcl, get_software_libdir('Tcl'))
            tk_libdir = os.path.join(tk, get_software_libdir('Tk'))
            tcltk_libs = "-L%(tcl_libdir)s -L%(tk_libdir)s -ltcl%(maj_min_ver)s -ltk%(maj_min_ver)s" % {
                'tcl_libdir': tcl_libdir,
                'tk_libdir': tk_libdir,
                'maj_min_ver': tcltk_maj_min_ver,
            }
            if LooseVersion(self.version) < '3.11':
                self.cfg.update('configopts', "--with-tcltk-includes='-I%s/include -I%s/include'" % (tcl, tk))
                self.cfg.update('configopts', "--with-tcltk-libs='%s'" % tcltk_libs)
            else:
                env.setvar('TCLTK_CFLAGS', '-I%s/include -I%s/include' % (tcl, tk))
                env.setvar('TCLTK_LIBS', tcltk_libs)

        # don't add user site directory to sys.path (equivalent to python -s)
        # This matters e.g. when python installs the bundled pip & setuptools (for >= 3.4)
        env.setvar('PYTHONNOUSERSITE', '1')

        super(EB_Python, self).configure_step()

    def build_step(self, *args, **kwargs):
        """Custom build procedure for Python, ensure stack size limit is set to 'unlimited' (if desired)."""

        # make sure installation directory doesn't already exist when building with --rpath and
        # configuring with --enable-optimizations, since that leads to errors like:
        #   ./python: symbol lookup error: ./python: undefined symbol: __gcov_indirect_call
        # see also https://bugs.python.org/issue29712
        enable_opts_flag = '--enable-optimizations'
        if build_option('rpath') and enable_opts_flag in self.cfg['configopts']:
            if os.path.exists(self.installdir):
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

        super(EB_Python, self).build_step(*args, **kwargs)

    @property
    def site_packages_path(self):
        return os.path.join('lib', 'python' + self.pyshortver, 'site-packages')

    def install_step(self):
        """Extend make install to make sure that the 'python' command is present."""

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        super(EB_Python, self).install_step()

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

    def _sanity_check_ebpythonprefixes(self):
        """Check that EBPYTHONPREFIXES works"""
        temp_prefix = tempfile.mkdtemp(suffix='-tmp-prefix')
        temp_site_packages_path = os.path.join(temp_prefix, self.site_packages_path)
        mkdir(temp_site_packages_path, parents=True)  # Must exist
        res = run_shell_cmd("%s=%s python -s -c 'import sys; print(sys.path)'" % (EBPYTHONPREFIXES, temp_prefix))
        out = res.output.strip()
        # Output should be a list which we can evaluate directly
        if not out.startswith('[') or not out.endswith(']'):
            raise EasyBuildError("Unexpected output for sys.path: %s", out)
        paths = eval(out)
        base_site_packages_path = os.path.join(self.installdir, self.site_packages_path)
        try:
            base_prefix_idx = paths.index(base_site_packages_path)
        except ValueError:
            raise EasyBuildError("The Python install path was not added to sys.path (%s)", paths)
        try:
            eb_prefix_idx = paths.index(temp_site_packages_path)
        except ValueError:
            raise EasyBuildError("EasyBuilds sitecustomize.py did not add %s to sys.path (%s)",
                                 temp_site_packages_path, paths)
        if eb_prefix_idx > base_prefix_idx:
            raise EasyBuildError("EasyBuilds sitecustomize.py did not add %s before %s to sys.path (%s)",
                                 temp_site_packages_path, base_site_packages_path, paths)

    def sanity_check_step(self):
        """Custom sanity check for Python."""

        shlib_ext = get_shared_lib_ext()

        try:
            fake_mod_data = self.load_fake_module()
        except EasyBuildError as err:
            raise EasyBuildError("Loading fake module failed: %s", err)

        abiflags = ''
        if LooseVersion(self.version) >= LooseVersion("3"):
            run_shell_cmd("command -v python", hidden=True)
            cmd = 'python -s -c "import sysconfig; print(sysconfig.get_config_var(\'abiflags\'));"'
            res = run_shell_cmd(cmd, hidden=True)
            abiflags = res.output
            if not abiflags:
                raise EasyBuildError("Failed to determine abiflags: %s", abiflags)
            else:
                abiflags = abiflags.strip()

        # make sure hashlib is installed correctly, there should be no errors/output when 'import hashlib' is run
        # (python will exit with 0 regardless of whether or not errors are printed...)
        # cfr. https://github.com/easybuilders/easybuild-easyconfigs/issues/6484
        cmd = "python -s -c 'import hashlib'"
        res = run_shell_cmd(cmd)
        out = res.output
        regex = re.compile('error', re.I)
        if regex.search(out):
            raise EasyBuildError("Found one or more errors in output of %s: %s", cmd, out)
        else:
            self.log.info("No errors found in output of %s: %s", cmd, out)

        if self.cfg.get('ebpythonprefixes'):
            self._sanity_check_ebpythonprefixes()

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
            "python -s -c 'import _ctypes'",  # make sure that foreign function interface (libffi) works
            "python -s -c 'import _ssl'",  # make sure SSL support is enabled one way or another
            "python -s -c 'import readline'",  # make sure readline support was built correctly
        ]

        if self.install_pip:
            # Check that pip and setuptools are installed
            py_maj_version = self.version.split('.')[0]
            custom_paths['files'].extend([
                os.path.join('bin', pip) for pip in ('pip', 'pip' + py_maj_version, 'pip' + self.pyshortver)
            ])
            custom_commands.extend([
                "python -s -c 'import pip'",
                "python -s -c 'import setuptools'",
            ])

        if get_software_root('Tk'):
            # also check whether importing tkinter module works, name is different for Python v2.x and v3.x
            if LooseVersion(self.version) >= LooseVersion('3'):
                tkinter = 'tkinter'
            else:
                tkinter = 'Tkinter'
            custom_commands.append("python -s -c 'import %s'" % tkinter)

            # check whether _tkinter*.so is found, exact filename doesn't matter
            tkinter_so = os.path.join(self.installdir, 'lib', pyver, 'lib-dynload', '_tkinter*.' + shlib_ext)
            tkinter_so_hits = glob.glob(tkinter_so)
            if len(tkinter_so_hits) == 1:
                self.log.info("Found exactly one _tkinter*.so: %s", tkinter_so_hits[0])
            else:
                raise EasyBuildError("Expected to find exactly one _tkinter*.so: %s", tkinter_so_hits)

        super(EB_Python, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
