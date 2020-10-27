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
EasyBuild support for building and installing binutils, implemented as an easyblock

@author: Kenneth Hoste (HPC-UGent)
"""
import glob
import os
import re
from distutils.version import LooseVersion

from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, copy_file
from easybuild.tools.modules import get_software_libdir, get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_shared_lib_ext


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

    def configure_step(self):
        """Custom configuration procedure for binutils: statically link to zlib, configure options."""

        # take sysroot configuration option into account;
        # make sure we don't use None going forward since the value is used in os.path.join expressions
        sysroot = build_option('sysroot') or os.path.sep

        libs = ''

        if self.toolchain.is_system_toolchain():
            # determine list of 'lib' directories to use rpath for;
            # this should 'harden' the resulting binutils to bootstrap GCC
            # (no trouble when other libstdc++ is build etc)

            # The installed lib dir must come first though to avoid taking system libs over installed ones, see:
            # https://github.com/easybuilders/easybuild-easyconfigs/issues/10056
            # Escaping: Double $$ for Make, \$ for shell to get literal $ORIGIN in the file
            libdirs = [r'\$\$ORIGIN/../lib']
            for libdir in ['lib', 'lib64', os.path.join('lib', 'x86_64-linux-gnu')]:

                libdir = os.path.join(sysroot, 'usr', libdir)

                # also consider /lib, /lib64 (without /usr/)
                alt_libdir = os.path.join(sysroot, libdir)

                if os.path.exists(libdir):
                    libdirs.append(libdir)
                    if os.path.exists(alt_libdir) and not os.path.samefile(libdir, alt_libdir):
                        libdirs.append(alt_libdir)

                elif os.path.exists(alt_libdir):
                    libdirs.append(alt_libdir)

            # Mind the single quotes
            libs += ' '.join("-Wl,-rpath='%s'" % libdir for libdir in libdirs)

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
                    libs += ' ' + libz_path

        # Using double quotes for LIBS to allow single quotes in libs
        self.cfg.update('preconfigopts', 'LIBS="%s"' % libs)
        self.cfg.update('prebuildopts', 'LIBS="%s"' % libs)

        # explicitly configure binutils to use / as sysroot
        # this is required to ensure the binutils installation works correctly with a (system)
        # GCC compiler that was explicitly configured with --with-sysroot=/;
        # we should *not* use the value of the EasyBuild --sysroot configuration option here,
        # since that leads to weird errors where the sysroot path is duplicated, like:
        #   /bin/ld.gold: error: cannot open /<sysroot>/<sysroot>/lib64/libc.so.6: No such file or directory
        self.cfg.update('configopts', '--with-sysroot=/')

        # build both static and shared libraries for recent binutils versions (default is only static)
        if LooseVersion(self.version) > LooseVersion('2.24'):
            self.cfg.update('configopts', "--enable-shared --enable-static")

        # enable gold linker with plugin support, use ld as default linker (for recent versions of binutils)
        if LooseVersion(self.version) > LooseVersion('2.24'):
            self.cfg.update('configopts', "--enable-gold --enable-plugins --enable-ld=default")

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
                copy_file(os.path.join(self.cfg['start_dir'], 'libiberty', 'libiberty.a'),
                          os.path.join(self.installdir, 'lib', 'libiberty.a'))

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
            binaries.append('ld.gold')
            lib_exts.append(shlib_ext)

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

        # if zlib is listed as a build dependency, it should have been linked in statically
        build_deps = self.cfg.dependencies(build_only=True)
        if any(dep['name'] == 'zlib' for dep in build_deps):
            for binary in binaries:
                bin_path = os.path.join(self.installdir, 'bin', binary)
                out, _ = run_cmd("file %s" % bin_path, simple=False)
                if re.search(r'statically linked', out):
                    # binary is fully statically linked, so no chance for dynamically linked libz
                    continue

                # check whether libz is linked dynamically, it shouldn't be
                out, _ = run_cmd("ldd %s" % bin_path, simple=False)
                if re.search(r'libz\.%s' % shlib_ext, out):
                    raise EasyBuildError("zlib is not statically linked in %s: %s", bin_path, out)

        super(EB_binutils, self).sanity_check_step(custom_paths=custom_paths)
