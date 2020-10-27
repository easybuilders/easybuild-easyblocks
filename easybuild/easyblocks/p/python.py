##
# Copyright 2009-2020 Ghent University
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
from distutils.version import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import build_option, log_path
from easybuild.tools.modules import get_software_libdir, get_software_root, get_software_version
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, mkdir
from easybuild.tools.filetools import read_file, remove_dir, symlink, write_file
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext
import easybuild.tools.toolchain as toolchain


EXTS_FILTER_PYTHON_PACKAGES = ('python -c "import %(ext_name)s"', "")

# magic value for unlimited stack size
UNLIMITED = 'unlimited'

EBPYTHONPREFIXES = 'EBPYTHONPREFIXES'

SITECUSTOMIZE = """
# sitecustomize.py script installed by EasyBuild,
# to support picking up Python packages which were installed
# for multiple Python versions in the same directory

import os
import site
import sys

# print debug messages when $EBPYTHONPREFIXES_DEBUG is defined
debug = os.getenv('%(EBPYTHONPREFIXES)s_DEBUG')

# use prefixes from $EBPYTHONPREFIXES, so they have lower priority than
# virtualenv-installed packages, unlike $PYTHONPATH

ebpythonprefixes = os.getenv('%(EBPYTHONPREFIXES)s')

if ebpythonprefixes:
    postfix = os.path.join('lib', 'python'+'.'.join(map(str,sys.version_info[:2])), 'site-packages')
    if debug:
        print("[%(EBPYTHONPREFIXES)s] postfix subdirectory to consider in installation directories: %%s" %% postfix)

    for prefix in ebpythonprefixes.split(os.pathsep):
        if debug:
            print("[%(EBPYTHONPREFIXES)s] prefix: %%s" %% prefix)
        sitedir = os.path.join(prefix, postfix)
        if os.path.isdir(sitedir):
            if debug:
                print("[%(EBPYTHONPREFIXES)s] adding site dir: %%s" %% sitedir)
            site.addsitedir(sitedir)
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

        self.pythonpath = None
        if self.cfg['ebpythonprefixes']:
            easybuild_subdir = log_path()
            self.pythonpath = os.path.join(easybuild_subdir, 'python')

    def patch_step(self, *args, **kwargs):
        """
        Custom patch step for Python:
        * patch setup.py when --sysroot EasyBuild configuration setting is used
        """

        super(EB_Python, self).patch_step(*args, **kwargs)

        # if we're installing Python with an alternate sysroot,
        # we need to patch setup.py which includes hardcoded paths like /usr/include and /lib64;
        # this fixes problems like not being able to build the _ssl module ("Could not build the ssl module")
        sysroot = build_option('sysroot')
        if sysroot:
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

            apply_regex_substitutions(setup_py_fn, regex_subs)

    def prepare_for_extensions(self):
        """
        Set default class and filter for Python packages
        """
        # build and install additional packages with PythonPackage easyblock
        self.cfg['exts_defaultclass'] = "PythonPackage"
        self.cfg['exts_filter'] = EXTS_FILTER_PYTHON_PACKAGES

        # don't pass down any build/install options that may have been specified
        # 'make' options do not make sense for when building/installing Python libraries (usually via 'python setup.py')
        msg = "Unsetting '%s' easyconfig parameter before building/installing extensions: %s"
        for param in ['buildopts', 'installopts']:
            if self.cfg[param]:
                self.log.debug(msg, param, self.cfg[param])
            self.cfg[param] = ''

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
            self.cfg.update('configopts', "--enable-optimizations")

        # Pip is included since 3.4 via ensurepip https://docs.python.org/3.4/whatsnew/changelog.html
        if LooseVersion(self.version) >= LooseVersion('3.4.0'):
            # Default, but do it explicitly
            self.cfg.update('configopts', "--with-ensurepip=upgrade")

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

            self.cfg.update('configopts', "--with-tcltk-includes='-I%s/include -I%s/include'" % (tcl, tk))

            tcl_libdir = os.path.join(tcl, get_software_libdir('Tcl'))
            tk_libdir = os.path.join(tk, get_software_libdir('Tk'))
            tcltk_libs = "-L%(tcl_libdir)s -L%(tk_libdir)s -ltcl%(maj_min_ver)s -ltk%(maj_min_ver)s" % {
                'tcl_libdir': tcl_libdir,
                'tk_libdir': tk_libdir,
                'maj_min_ver': tcltk_maj_min_ver,
            }
            self.cfg.update('configopts', "--with-tcltk-libs='%s'" % tcltk_libs)

        # don't add user site directory to sys.path (equivalent to python -s)
        # This matters e.g. when python installs the bundled pip & setuptools (for >= 3.4)
        env.setvar('PYTHONNOUSERSITE', '1', verbose=False)

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
            (out, _) = run_cmd("ulimit -s")
            curr_ulimit_s = out.strip()

            # figure out hard limit for stack size limit;
            # this determines whether or not we can use "ulimit -s unlimited"
            (out, _) = run_cmd("ulimit -s -H")
            max_ulimit_s = out.strip()

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

    def install_step(self):
        """Extend make install to make sure that the 'python' command is present."""

        # avoid that pip (ab)uses $HOME/.cache/pip
        # cfr. https://pip.pypa.io/en/stable/reference/pip_install/#caching
        env.setvar('XDG_CACHE_HOME', tempfile.gettempdir())
        self.log.info("Using %s as pip cache directory", os.environ['XDG_CACHE_HOME'])

        super(EB_Python, self).install_step()

        python_binary_path = os.path.join(self.installdir, 'bin', 'python')
        if not os.path.isfile(python_binary_path):
            symlink(python_binary_path + self.pyshortver, python_binary_path)

        if self.cfg['ebpythonprefixes']:
            write_file(os.path.join(self.installdir, self.pythonpath, 'sitecustomize.py'), SITECUSTOMIZE)

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

    def sanity_check_step(self):
        """Custom sanity check for Python."""

        shlib_ext = get_shared_lib_ext()

        try:
            fake_mod_data = self.load_fake_module()
        except EasyBuildError as err:
            raise EasyBuildError("Loading fake module failed: %s", err)

        abiflags = ''
        if LooseVersion(self.version) >= LooseVersion("3"):
            run_cmd("which python", log_all=True, simple=False, trace=False)
            cmd = 'python -c "import sysconfig; print(sysconfig.get_config_var(\'abiflags\'));"'
            (abiflags, _) = run_cmd(cmd, log_all=True, simple=False, trace=False)
            if not abiflags:
                raise EasyBuildError("Failed to determine abiflags: %s", abiflags)
            else:
                abiflags = abiflags.strip()

        # make sure hashlib is installed correctly, there should be no errors/output when 'import hashlib' is run
        # (python will exit with 0 regardless of whether or not errors are printed...)
        # cfr. https://github.com/easybuilders/easybuild-easyconfigs/issues/6484
        cmd = "python -c 'import hashlib'"
        (out, _) = run_cmd(cmd)
        regex = re.compile('error', re.I)
        if regex.search(out):
            raise EasyBuildError("Found one or more errors in output of %s: %s", cmd, out)
        else:
            self.log.info("No errors found in output of %s: %s", cmd, out)

        pyver = 'python' + self.pyshortver
        custom_paths = {
            'files': [os.path.join('bin', pyver), os.path.join('lib', 'lib' + pyver + abiflags + '.' + shlib_ext)],
            'dirs': [os.path.join('include', pyver + abiflags), os.path.join('lib', pyver, 'lib-dynload')],
        }

        # cleanup
        self.clean_up_fake_module(fake_mod_data)

        custom_commands = [
            "python --version",
            "python -c 'import _ctypes'",  # make sure that foreign function interface (libffi) works
            "python -c 'import _ssl'",  # make sure SSL support is enabled one way or another
            "python -c 'import readline'",  # make sure readline support was built correctly
        ]

        if LooseVersion(self.version) >= LooseVersion('3.4.0'):
            # Check that pip and setuptools are installed
            custom_paths['files'].extend([
                os.path.join('bin', pip) for pip in ('pip', 'pip3', 'pip' + self.pyshortver)
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

        super(EB_Python, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self, *args, **kwargs):
        """Add path to sitecustomize.py to $PYTHONPATH"""
        txt = super(EB_Python, self).make_module_extra()

        if self.pythonpath:
            txt += self.module_generator.prepend_paths('PYTHONPATH', self.pythonpath)

        return txt
