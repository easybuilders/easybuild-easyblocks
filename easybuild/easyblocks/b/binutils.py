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
EasyBuild support for building and installing binutils, implemented as an easyblock

@author: Kenneth Hoste (HPC-UGent)
"""
import glob
import os
import re
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import apply_regex_substitutions, copy_file
from easybuild.tools.modules import get_software_libdir, get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import RISCV, get_cpu_family, get_shared_lib_ext
from easybuild.tools.utilities import nub


class EB_binutils(ConfigureMake):
    """Support for building/installing binutils."""

    @staticmethod
    def extra_options(extra_vars=None):
        """Extra easyconfig parameters specific to the binutils easyblock."""
        extra_vars = ConfigureMake.extra_options(extra_vars=extra_vars)
        extra_vars.update({
            'install_libiberty': [True, "Also install libiberty (implies building with -fPIC)", CUSTOM],
            'use_debuginfod': [False, "Build with debuginfod (used from system)", CUSTOM],
        })
        return extra_vars

    def __init__(self, *args, **kwargs):
        """Easyblock constructor"""
        super(EB_binutils, self).__init__(*args, **kwargs)

        # ld.gold linker is not supported on RISC-V
        self.use_gold = get_cpu_family() != RISCV

    def determine_used_library_paths(self):
        """Check which paths are used to search for libraries"""

        # determine C compiler command: use $CC, fall back to 'gcc' (when using system toolchain)
        compiler_cmd = os.environ.get('CC', 'gcc')

        # determine library search paths for GCC
        res = run_shell_cmd('LC_ALL=C "%s" -print-search-dirs' % compiler_cmd)
        if res.exit_code:
            raise EasyBuildError("Failed to determine library search dirs from compiler %s", compiler_cmd)

        m = re.search('^libraries: *=(.*)$', res.output, re.M)
        paths = nub(os.path.abspath(p) for p in m.group(1).split(os.pathsep))
        self.log.debug('Unique library search paths from compiler %s: %s', compiler_cmd, paths)

        # Filter out all paths that do not exist
        paths = [p for p in paths if os.path.exists(p)]
        self.log.debug("Existing library search paths: %s", ', '.join(paths))

        result = []
        for path in paths:
            if any(os.path.samefile(path, p) for p in result):
                self.log.debug("Skipping symlink to existing path: %s", path)
            elif not glob.glob(os.path.join(path, '*.so*')):
                self.log.debug("Skipping path with no shared libraries: %s", path)
            else:
                result.append(path)

        self.log.info("Determined library search paths: %s", ', '.join(result))
        return result

    def configure_step(self):
        """Custom configuration procedure for binutils: statically link to zlib, configure options."""

        if self.toolchain.is_system_toolchain():
            # determine list of 'lib' directories to use rpath for;
            # this should 'harden' the resulting binutils to bootstrap GCC
            # (no trouble when other libstdc++ is build etc)
            lib_paths = self.determine_used_library_paths()

            # The installed lib dir must come first though to avoid taking system libs over installed ones, see:
            # https://github.com/easybuilders/easybuild-easyconfigs/issues/10056
            # To get literal $ORIGIN through Make we need to escape it by doubling $$, else it's a variable to Make;
            # We need to include both 'lib' and 'lib64' here, to ensure this works as intended
            # across different operating systems,
            # see https://github.com/easybuilders/easybuild-easyconfigs/issues/11976
            lib_paths = [r'$$ORIGIN/../lib', r'$$ORIGIN/../lib64'] + lib_paths
            # Mind the single quotes
            libs = ["-Wl,-rpath='%s'" % x for x in lib_paths]
        else:
            libs = []

        binutilsroot = get_software_root('binutils')
        if binutilsroot:
            # Remove LDFLAGS that start with '-L' + binutilsroot, since we don't
            # want to link libraries from binutils compiled with the system toolchain
            # into binutils binaries compiled with a compiler toolchain.
            ldflags = os.getenv('LDFLAGS').split(' ')
            ldflags = [p for p in ldflags if not p.startswith('-L' + binutilsroot)]
            env.setvar('LDFLAGS', ' '.join(ldflags))

        # configure using `--with-system-zlib` if zlib is a (build) dependency
        zlibroot = get_software_root('zlib')
        if zlibroot:
            self.cfg.update('configopts', '--with-system-zlib')

            # statically link to zlib only if it is a build dependency
            # see https://github.com/easybuilders/easybuild-easyblocks/issues/1350
            build_deps = self.cfg.dependencies(build_only=True)
            if any(dep['name'] == 'zlib' for dep in build_deps):
                libz_path = os.path.join(zlibroot, get_software_libdir('zlib'), 'libz.a')

                # for recent binutils versions, we need to override ZLIB in Makefile.in of components
                if LooseVersion(self.version) >= LooseVersion('2.26'):
                    regex_subs = [
                        (r"^(ZLIB\s*=\s*).*$", r"\1%s" % libz_path),
                        (r"^(ZLIBINC\s*=\s*).*$", r"\1-I%s" % os.path.join(zlibroot, 'include')),
                    ]
                    for makefile in glob.glob(os.path.join(self.cfg['start_dir'], '*', 'Makefile.in')):
                        apply_regex_substitutions(makefile, regex_subs)

                # for older versions, injecting the path to the static libz library into $LIBS works
                else:
                    libs.append(libz_path)

        msgpackroot = get_software_root('msgpack-c')
        if LooseVersion(self.version) >= LooseVersion('2.39'):
            if msgpackroot:
                self.cfg.update('configopts', '--with-msgpack')
            else:
                self.cfg.update('configopts', '--without-msgpack')
        elif msgpackroot:
            raise EasyBuildError('msgpack is only supported since binutils 2.39. Remove the dependency!')

        env.setvar('LIBS', ' '.join(libs))

        # explicitly configure binutils to use / as sysroot
        # this is required to ensure the binutils installation works correctly with a (system)
        # GCC compiler that was explicitly configured with --with-sysroot=/;
        # we should *not* use the value of the EasyBuild --sysroot configuration option here,
        # since that leads to weird errors where the sysroot path is duplicated, like:
        #   /bin/ld.gold: error: cannot open /<sysroot>/<sysroot>/lib64/libc.so.6: No such file or directory
        # (see also https://gcc.gnu.org/legacy-ml/gcc-help/2006-08/msg00212.html)
        self.cfg.update('configopts', '--with-sysroot=/')

        # build both static and shared libraries for recent binutils versions (default is only static)
        if LooseVersion(self.version) > LooseVersion('2.24'):
            self.cfg.update('configopts', "--enable-shared --enable-static")

        # enable gold linker with plugin support, use ld as default linker (for recent versions of binutils)
        if LooseVersion(self.version) > LooseVersion('2.24'):
            self.cfg.update('configopts', "--enable-plugins --enable-ld=default")
            if self.use_gold:
                self.cfg.update('configopts', '--enable-gold')

        if LooseVersion(self.version) >= LooseVersion('2.34'):
            if self.cfg['use_debuginfod']:
                self.cfg.update('configopts', '--with-debuginfod')
            else:
                self.cfg.update('configopts', '--without-debuginfod')

        # complete configuration with configure_method of parent
        super(EB_binutils, self).configure_step()

        if self.cfg['install_libiberty']:
            cflags = os.getenv('CFLAGS')
            if cflags:
                self.cfg.update('buildopts', 'CFLAGS="$CFLAGS -fPIC"')
            else:
                # if $CFLAGS is not defined, make sure we retain "-g -O2",
                # since not specifying any optimization level implies -O0...
                self.cfg.update('buildopts', 'CFLAGS="-g -O2 -fPIC"')

    def install_step(self):
        """Install using 'make install', also install libiberty if desired."""
        super(EB_binutils, self).install_step()

        # only install libiberty files if if they're not there yet;
        # libiberty.a is installed by default for old binutils versions
        if self.cfg['install_libiberty']:
            if not os.path.exists(os.path.join(self.installdir, 'include', 'libiberty.h')):
                copy_file(os.path.join(self.cfg['start_dir'], 'include', 'libiberty.h'),
                          os.path.join(self.installdir, 'include', 'libiberty.h'))

            if not glob.glob(os.path.join(self.installdir, 'lib*', 'libiberty.a')):
                # Be a bit careful about where we install into
                libdir = os.path.join(self.installdir, 'lib')
                # At this point the lib directory should exist and be populated, if not try the other option
                if not (os.path.exists(libdir) and os.path.isdir(libdir) and os.listdir(libdir)):
                    libdir = os.path.join(self.installdir, 'lib64')

                # Make sure the target exists (it should, otherwise our sanity check will fail)
                if os.path.exists(libdir) and os.path.isdir(libdir) and os.listdir(libdir):
                    copy_file(os.path.join(self.cfg['start_dir'], 'libiberty', 'libiberty.a'),
                              os.path.join(libdir, 'libiberty.a'))
                else:
                    raise EasyBuildError("Target installation directory %s for libiberty.a is non-existent or empty",
                                         libdir)

            if not os.path.exists(os.path.join(self.installdir, 'info', 'libiberty.texi')):
                copy_file(os.path.join(self.cfg['start_dir'], 'libiberty', 'libiberty.texi'),
                          os.path.join(self.installdir, 'info', 'libiberty.texi'))

    def sanity_check_step(self):
        """Custom sanity check for binutils."""

        binaries = ['addr2line', 'ar', 'as', 'c++filt', 'elfedit', 'gprof', 'ld', 'ld.bfd', 'nm',
                    'objcopy', 'objdump', 'ranlib', 'readelf', 'size', 'strings', 'strip']

        headers = ['ansidecl.h', 'bfd.h', 'bfdlink.h', 'dis-asm.h', 'symcat.h']
        libs = ['bfd', 'opcodes']

        lib_exts = ['a']
        shlib_ext = get_shared_lib_ext()

        if LooseVersion(self.version) > LooseVersion('2.24'):
            lib_exts.append(shlib_ext)
            if self.use_gold:
                binaries.append('ld.gold')

        bin_paths = [os.path.join('bin', b) for b in binaries]
        inc_paths = [os.path.join('include', h) for h in headers]

        libs_fn = ['lib%s.%s' % (lib, ext) for lib in libs for ext in lib_exts]
        lib_paths = [(os.path.join('lib', lib_fn), os.path.join('lib64', lib_fn)) for lib_fn in libs_fn]

        custom_paths = {
            'files': bin_paths + inc_paths + lib_paths,
            'dirs': [],
        }

        if self.cfg['install_libiberty']:
            custom_paths['files'].extend([
                (os.path.join('lib', 'libiberty.a'), os.path.join('lib64', 'libiberty.a')),
                os.path.join('include', 'libiberty.h'),
            ])

        # All binaries support --version, check that they can be run
        custom_commands = ['%s --version' % b for b in binaries]

        # if zlib is listed as a build dependency, it should have been linked in statically
        build_deps = self.cfg.dependencies(build_only=True)
        if any(dep['name'] == 'zlib' for dep in build_deps):
            for binary in binaries:
                bin_path = os.path.join(self.installdir, 'bin', binary)
                res = run_shell_cmd("file %s" % bin_path)
                if re.search(r'statically linked', res.output):
                    # binary is fully statically linked, so no chance for dynamically linked libz
                    continue

                # check whether libz is linked dynamically, it shouldn't be
                res = run_shell_cmd("ldd %s" % bin_path)
                if re.search(r'libz\.%s' % shlib_ext, res.output):
                    raise EasyBuildError("zlib is not statically linked in %s: %s", bin_path, res.output)

        super(EB_binutils, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)
