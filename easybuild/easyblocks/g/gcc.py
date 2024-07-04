##
# Copyright 2009-2024 Ghent University
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
EasyBuild support for building and installing GCC, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Toon Willems (Ghent University)
@author: Ward Poelmans (Ghent University)
@author: Bart Oldeman (McGill University, Calcul Quebec, Compute Canada)
"""
import glob
import os
import re
import shutil
import stat
from copy import copy
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
from easybuild.easyblocks.clang import DEFAULT_TARGETS_MAP as LLVM_ARCH_MAP
from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, adjust_permissions, change_dir, copy_file
from easybuild.tools.filetools import mkdir, move_file, read_file, symlink, which, write_file
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import RISCV, check_os_dependency, get_cpu_architecture, get_cpu_family
from easybuild.tools.systemtools import get_gcc_version, get_shared_lib_ext, get_os_name, get_os_type
from easybuild.tools.toolchain.compiler import OPTARCH_GENERIC
from easybuild.tools.utilities import nub


# Offloading stages to build
AMD_LLVM = 'AMD_GCN_LLVM'
AMD_NEWLIB = 'AMD_GCN_NEWLIB'
HOST_COMPILER = 'HOST_COMPILER'
NVIDIA_NEWLIB = 'NVIDIA_NEWLIB'
NVPTX_TOOLS = 'NVIDIA_NVPTX_TOOLS'
# Additional symlinks to create for compiler commands
COMP_CMD_SYMLINKS = {
    'cc': 'gcc',
    'c++': 'g++',
    'f77': 'gfortran',
    'f95': 'gfortran',
}

RECREATE_INCLUDE_FIXED_SCRIPT_TMPL = """#!/bin/bash

# Script to (re)generate fixed headers in include-fixed subdirectory of GCC installation

set -u

gccInstallDir=$(dirname "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")")
mkheadersPath="$gccInstallDir/%(relative_mkheaders)s"
includesFixedDir="$gccInstallDir/%(relative_include_fixed)s"

if [[ ! -f "$mkheadersPath" ]]; then
    echo "mkheaders not found in '$(dirname "$mkheadersPath")'" >&2
    exit 1
fi

if [[ -d "$includesFixedDir" && ! -w "$includesFixedDir" ]]; then
    resetReadOnly=1
    echo "Found READONLY $includesFixedDir. Adding write permissions"
    if ! chmod -R u+w "$includesFixedDir"; then
        echo "$includesFixedDir is readonly and failed to change that automatically." >&2
        echo "Add write permissions manually and rerun this script." >&2
        exit 1
    fi
else
    resetReadOnly=0
fi

readmePath="$includesFixedDir/README"
if [[ -f $readmePath ]]; then
    tmpReadmePath=$(mktemp)
    cp "$readmePath" "$tmpReadmePath"
else
    tmpReadmePath=""
fi

echo "Starting $mkheadersPath $*"
"$mkheadersPath" "$@"
ec=$?

if [[ -n "$tmpReadmePath" && -f "$tmpReadmePath" ]]; then
    mv -f "$tmpReadmePath" "$readmePath"
fi

if [[ $resetReadOnly -eq 1 ]] && ! chmod -R u-w "$includesFixedDir"; then
    echo "Failed to set $includesFixedDir as readonly again after adding write permissions." >&2
    echo "Ensure the permissions are set as required!" >&2
    exit 1
fi

exit $ec
"""


class EB_GCC(ConfigureMake):
    """
    Self-contained build of GCC.
    Uses system compiler for initial build, then bootstraps.
    """

    @staticmethod
    def extra_options():
        extra_vars = {
            'clooguseisl': [False, "Use ISL with CLooG or not", CUSTOM],
            'generic': [None, "Build GCC and support libraries such that it runs on all processors of the target "
                              "architecture (use False to enforce non-generic regardless of configuration)", CUSTOM],
            'rename_include_fixed': [False, "Rename the 'include-fixed' directory to avoid that it is used by GCC. "
                                            "This avoids issues when upgrading the OS but might limit the "
                                            "functionality of GCC, especially if the OS GLIBC is older than GCC. "
                                            "A script to (re-)generate the include-fixed folder is created in the "
                                            "'easybuild' subfolder inside the installation directory.", CUSTOM],
            'languages': [[], "List of languages to build GCC for (--enable-languages)", CUSTOM],
            'multilib': [False, "Build multilib gcc (both i386 and x86_64)", CUSTOM],
            'pplwatchdog': [False, "Enable PPL watchdog", CUSTOM],
            'prefer_lib_subdir': [False, "Configure GCC to prefer 'lib' subdirs over 'lib64' when linking", CUSTOM],
            'profiled': [False, "Bootstrap GCC with profile-guided optimizations", CUSTOM],
            'use_gold_linker': [None, "Configure GCC to use GOLD as default linker "
                                      "(default: enable automatically for GCC < 11.3.0, except on RISC-V)", CUSTOM],
            'withcloog': [False, "Build GCC with CLooG support", CUSTOM],
            'withisl': [False, "Build GCC with ISL support", CUSTOM],
            'withlibiberty': [False, "Enable installing of libiberty", CUSTOM],
            'withlto': [True, "Enable LTO support", CUSTOM],
            'withppl': [False, "Build GCC with PPL support", CUSTOM],
            'withnvptx': [False, "Build GCC with NVPTX offload support", CUSTOM],
            'withamdgcn': [False, "Build GCC with AMD GCN offload support", CUSTOM],
        }
        return ConfigureMake.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        super(EB_GCC, self).__init__(*args, **kwargs)

        self.stagedbuild = False
        # Each build iteration is related to a specific build, first build host compiler, then potentially build NVPTX
        # offloading and/or AMD GCN offloading
        self.build_stages = [HOST_COMPILER]
        self.current_stage = HOST_COMPILER
        # Directories for additional tools needed when doing offloading to Nvidia and AMD
        self.nvptx_tools_dir = None  # nvptx-tools necessary for Nvidia
        self.llvm_dir = None  # LLVM is necessary when offloading to AMD
        self.lld_dir = None  # LLD is the only required component of LLVM
        self.newlib_dir = None  # Used by both NVPTX and AMD GCN backend

        # need to make sure version is an actual version
        # required because of support in SystemCompiler generic easyblock to specify 'system' as version,
        # which results in deriving the actual compiler version
        # comparing a non-version like 'system' with an actual version like '2016' fails with TypeError in Python 3.x
        if re.match(r'^[0-9]+\.[0-9]+.*', self.version):
            version = LooseVersion(self.version)

            if version >= LooseVersion('4.8.0') and self.cfg['clooguseisl'] and not self.cfg['withisl']:
                raise EasyBuildError("Using ISL bundled with CLooG is unsupported in >=GCC-4.8.0. "
                                     "Use a seperate ISL: set withisl=True")

            # I think ISL without CLooG has no purpose in GCC < 5.0.0 ...
            if version < LooseVersion('5.0.0') and self.cfg['withisl'] and not self.cfg['withcloog']:
                raise EasyBuildError("Activating ISL without CLooG is pointless")

            # Disable the Gold linker by default for GCC 11.3.0 and newer, as it suffers from bitrot
            if self.cfg['use_gold_linker'] is None:
                self.cfg['use_gold_linker'] = version < LooseVersion('11.3.0')

        # unset some environment variables that are known to may cause nasty build errors when bootstrapping
        self.cfg.update('unwanted_env_vars', ['CPATH', 'C_INCLUDE_PATH', 'CPLUS_INCLUDE_PATH', 'OBJC_INCLUDE_PATH'])
        # ubuntu needs the LIBRARY_PATH env var to work apparently (#363)
        if get_os_name() not in ['ubuntu', 'debian']:
            self.cfg.update('unwanted_env_vars', ['LIBRARY_PATH'])

        # disable NVPTX on RISC-V
        if get_cpu_family() == RISCV:
            self.log.warning('Setting withnvptx to False, since we are building on a RISC-V system')
            self.cfg['withnvptx'] = False

    def create_dir(self, dirname):
        """
        Create a dir to build in.
        """
        dirpath = os.path.join(self.cfg['start_dir'], dirname)
        try:
            mkdir(dirpath)
            change_dir(dirpath)
            self.log.debug("Created dir at %s" % dirpath)
            return dirpath
        except OSError as err:
            raise EasyBuildError("Can't use dir %s to build in: %s", dirpath, err)

    def disable_lto_mpfr_old_gcc(self, objdir):
        """
        # if GCC version used to build stage 1 is too old, build MPFR without LTO in stage 1
        # required for e.g. CentOS 6, cfr. https://github.com/easybuilders/easybuild-easyconfigs/issues/6374
        """
        self.log.info("Checking whether we are trying to build a recent MPFR with an old GCC...")

        # try to figure out MPFR version being built
        mpfr_ver = '0.0'
        mpfr_dirs = glob.glob(os.path.join(self.builddir, 'mpfr-*'))
        if len(mpfr_dirs) == 1:
            mpfr_dir = mpfr_dirs[0]
            res = re.search('(?P<mpfr_ver>[0-9.]+)$', mpfr_dir)
            if res:
                mpfr_ver = res.group('mpfr_ver')
                self.log.info("Found MPFR version %s (based name of MPFR source dir: %s)", mpfr_ver, mpfr_dir)
            else:
                self.log.warning("Failed to determine MPFR version from '%s', assuming v%s", mpfr_dir, mpfr_ver)
        else:
            self.log.warning("Failed to isolate MPFR source dir to determine MPFR version, assuming v%s", mpfr_ver)

        # for MPFR v4.x & newer, we need a recent GCC that supports -flto
        if LooseVersion(mpfr_ver) >= LooseVersion('4.0'):

            disable_mpfr_lto = False

            # check GCC version being used
            # GCC 4.5 is required for -flto (cfr. https://gcc.gnu.org/gcc-4.5/changes.html)
            gcc_ver = get_gcc_version()
            min_gcc_ver_lto = '4.5'
            if gcc_ver is None:
                self.log.warning("Failed to determine GCC version, assuming it's recent enough...")
            elif LooseVersion(gcc_ver) < LooseVersion(min_gcc_ver_lto):
                self.log.info("Configuring MPFR to build without LTO in stage 1 (GCC %s is too old: < %s)!",
                              gcc_ver, min_gcc_ver_lto)
                disable_mpfr_lto = True
            else:
                self.log.info("GCC %s (>= %s) is OK for building MPFR in stage 1 with LTO enabled",
                              gcc_ver, min_gcc_ver_lto)

                # check whether GCC actually supports LTO (it may be configured with --disable-lto),
                # by compiling a simple C program using -flto
                out, ec = run_cmd("echo 'void main() {}' | gcc -x c -flto - -o /dev/null", simple=False, log_ok=False)
                gcc_path = which('gcc')
                if ec:
                    self.log.info("GCC command %s doesn't seem to support LTO, test compile failed: %s", gcc_path, out)
                    disable_mpfr_lto = True
                else:
                    self.log.info("GCC command %s provides LTO support, so using it when building MPFR", gcc_path)

            if disable_mpfr_lto:
                # patch GCC's Makefile to inject --disable-lto when building MPFR
                stage1_makefile = os.path.join(objdir, 'Makefile')
                regex_subs = [(r'(--with-gmp-lib=\$\$r/\$\(HOST_SUBDIR\)/gmp/.libs) \\', r'\1 --disable-lto \\')]
                apply_regex_substitutions(stage1_makefile, regex_subs)

    def prep_extra_src_dirs(self, stage, target_prefix=None):
        """
        Prepare extra (optional) source directories, so GCC will build these as well.
        """
        if LooseVersion(self.version) >= LooseVersion('4.5'):
            known_stages = ["stage1", "stage2", "stage3"]
            if stage not in known_stages:
                raise EasyBuildError("Incorrect argument for prep_extra_src_dirs, should be one of: %s", known_stages)

            configopts = ''
            if stage == "stage2":
                # no MPFR/MPC needed in stage 2
                extra_src_dirs = ["gmp"]
            else:
                extra_src_dirs = ["gmp", "mpfr", "mpc"]

            # list of the extra dirs that are needed depending on the 'with%s' option
            # the order is important: keep CLooG last!
            self.with_dirs = ["isl", "ppl", "cloog"]

            # add optional ones that were selected (e.g. CLooG, PPL, ...)
            for x in self.with_dirs:
                if self.cfg['with%s' % x]:
                    extra_src_dirs.append(x)

            # see if modules are loaded
            # if module is available, just use the --with-X GCC configure option
            for extra in copy(extra_src_dirs):
                envvar = get_software_root(extra)
                if envvar:
                    configopts += " --with-%s=%s" % (extra, envvar)
                    extra_src_dirs.remove(extra)
                elif extra in self.with_dirs and stage in ["stage1", "stage3"]:
                    # building CLooG or PPL or ISL requires a recent compiler
                    # our best bet is to do a 3-staged build of GCC, and
                    # build CLooG/PPL/ISL with the GCC we're building in stage 2
                    # then (bootstrap) build GCC in stage 3
                    # also, no need to stage cloog/ppl/isl in stage3 (may even cause troubles)
                    self.stagedbuild = True
                    extra_src_dirs.remove(extra)

            # try and find source directories with given prefixes
            # these sources should be included in list of sources in .eb spec file,
            # so EasyBuild can unpack them in the build dir
            found_src_dirs = []
            versions = {}
            names = {}
            all_dirs = os.listdir(self.builddir)
            for d in all_dirs:
                for sd in extra_src_dirs:
                    if d.startswith(sd):
                        found_src_dirs.append({
                            'source_dir': d,
                            'target_dir': sd
                        })
                        # expected format: get_name[-subname]-get_version
                        ds = os.path.basename(d).split('-')
                        name = '-'.join(ds[0:-1])
                        names.update({sd: name})
                        ver = ds[-1]
                        versions.update({sd: ver})

            # we need to find all dirs specified, or else...
            if not len(found_src_dirs) == len(extra_src_dirs):
                raise EasyBuildError("Couldn't find all source dirs %s: found %s from %s",
                                     extra_src_dirs, found_src_dirs, all_dirs)

            # copy to a dir with name as expected by GCC build framework
            for d in found_src_dirs:
                src = os.path.join(self.builddir, d['source_dir'])
                if target_prefix:
                    dst = os.path.join(target_prefix, d['target_dir'])
                else:
                    dst = os.path.join(self.cfg['start_dir'], d['target_dir'])
                if not os.path.exists(dst):
                    try:
                        shutil.copytree(src, dst)
                    except OSError as err:
                        raise EasyBuildError("Failed to copy src %s to dst %s: %s", src, dst, err)
                    self.log.debug("Copied %s to %s, so GCC can build %s" % (src, dst, d['target_dir']))
                else:
                    self.log.debug("No need to copy %s to %s, it's already there." % (src, dst))
        else:
            # in versions prior to GCC v4.5, there's no support for extra source dirs, so return only empty info
            configopts = ''
            names = {}
            versions = {}

        return {
            'configopts': configopts,
            'names': names,
            'versions': versions
        }

    def run_configure_cmd(self, cmd):
        """
        Run a configure command, with some extra checking (e.g. for unrecognized options).
        """
        # note: this also triggers the use of an updated config.guess script
        # (unless both the 'build_type' and 'host_type' easyconfig parameters are specified)
        build_type, host_type = self.determine_build_and_host_type()
        if build_type:
            cmd += ' --build=' + build_type
        if host_type:
            cmd += ' --host=' + host_type

        (out, ec) = run_cmd("%s %s" % (self.cfg['preconfigopts'], cmd), log_all=True, simple=False)

        if ec != 0:
            raise EasyBuildError("Command '%s' exited with exit code != 0 (%s)", cmd, ec)

        # configure scripts tend to simply ignore unrecognized options
        # we should be more strict here, because GCC is very much a moving target
        unknown_re = re.compile("WARNING: unrecognized options")

        unknown_options = unknown_re.findall(out)
        if unknown_options:
            raise EasyBuildError("Unrecognized options found during configure: %s", unknown_options)

    def prepare_step(self, *args, **kwargs):
        """
        Prepare build environment, track currently active build stage
        """
        super(EB_GCC, self).prepare_step(*args, **kwargs)

        # Set the current build stage to the specified stage based on the iteration index
        self.current_stage = self.build_stages[self.iter_idx]

    def configure_step(self):
        """
        Configure for GCC build:
        - prepare extra source dirs (GMP, MPFR, MPC, ...)
        - create obj dir to build in (GCC doesn't like to be built in source dir)
        - add configure and make options, according to .eb spec file
        - decide whether or not to do a staged build (which is required to enable PPL/CLooG support)
        - set platform_lib based on config.guess output
        """

        sysroot = build_option('sysroot')
        if sysroot:
            # based on changes made to GCC in Gentoo Prefix
            # https://gitweb.gentoo.org/repo/gentoo.git/tree/profiles/features/prefix/standalone/profile.bashrc

            # add --with-sysroot configure option, to instruct GCC to consider
            # value set for EasyBuild's --sysroot configuration option as the root filesystem of the operating system
            # (see https://gcc.gnu.org/install/configure.html)
            self.cfg.update('configopts', '--with-sysroot=%s' % sysroot)

            libc_so_candidates = [os.path.join(sysroot, x, 'libc.so') for x in
                                  ['lib', 'lib64', os.path.join('usr', 'lib'), os.path.join('usr', 'lib64')]]
            for libc_so in libc_so_candidates:
                if os.path.exists(libc_so):
                    # only patch gcc.c or gcc.cc if entries in libc.so are prefixed with sysroot
                    if '\nGROUP ( ' + sysroot in read_file(libc_so):
                        gccfile = os.path.join('gcc', 'gcc.c')
                        # renamed to gcc.cc in GCC 12
                        if not os.path.exists(gccfile):
                            gccfile = os.path.join('gcc', 'gcc.cc')
                        # avoid that --sysroot is passed to linker by patching value for SYSROOT_SPEC in gcc/gcc.c*
                        apply_regex_substitutions(gccfile, [('--sysroot=%R', '')])
                    break

            # prefix dynamic linkers with sysroot
            # this patches lines like:
            # #define GLIBC_DYNAMIC_LINKER64 "/lib64/ld-linux-x86-64.so.2"
            # for PowerPC (rs6000) we have to set DYNAMIC_LINKER_PREFIX to sysroot
            gcc_config_headers = glob.glob(os.path.join('gcc', 'config', '*', '*linux*.h'))
            regex_subs = [
                ('(_DYNAMIC_LINKER.*[":])/lib', r'\1%s/lib' % sysroot),
                ('(DYNAMIC_LINKER_PREFIX\\s+)""', r'\1"%s"' % sysroot),
            ]
            for gcc_config_header in gcc_config_headers:
                apply_regex_substitutions(gcc_config_header, regex_subs)

        # self.configopts will be reused in a 3-staged build,
        # configopts is only used in first configure
        self.configopts = self.cfg['configopts']

        # I) prepare extra source dirs, e.g. for GMP, MPFR, MPC (if required), so GCC can build them
        stage1_info = self.prep_extra_src_dirs("stage1")
        configopts = stage1_info['configopts']

        # II) update config options

        # enable specified language support
        if self.cfg['languages']:
            self.configopts += " --enable-languages=%s" % ','.join(self.cfg['languages'])

        if self.cfg['withnvptx'] or self.cfg['withamdgcn']:

            # Check that sources for optional dependencies for NVPTX and/or AMD GCN offload support are available
            source_deps = [
                (['withnvptx'], 'nvptx-tools', 'nvptx_tools_dir'),
                (['withamdgcn'], 'LLD', 'lld_dir'),
                (['withamdgcn'], 'LLVM', 'llvm_dir'),
                (['withamdgcn', 'withnvptx'], 'newlib', 'newlib_dir'),
            ]

            for (with_opts, dep_name, target_var_name) in source_deps:
                if any(self.cfg[x] for x in with_opts):
                    hits = glob.glob(os.path.join(self.builddir, dep_name.lower() + '-*'))
                    if len(hits) == 1:
                        setattr(self, target_var_name, hits[0])
                        self.log.info("Found sources for %s at %s (%s)", dep_name, hits[0], target_var_name)
                    else:
                        with_opts_or = ' or '.join("'%s'" % x for x in with_opts)
                        error_msg = "Easyconfig enables %s, " % with_opts_or
                        error_msg += "but '%s' sources were not found. " % dep_name
                        error_msg += "Make sure that sources for %s are listed in the easyconfig file!" % dep_name
                        raise EasyBuildError(error_msg)

            if self.current_stage == HOST_COMPILER:
                self.configopts += " --without-cuda-driver"
                offload_target = []
                if self.cfg['withnvptx']:
                    offload_target += ['nvptx-none']
                if self.cfg['withamdgcn']:
                    offload_target += ['amdgcn-amdhsa']
                self.configopts += " --enable-offload-targets=%s" % ','.join(offload_target)
            else:
                # register installed GCC as compiler to use nvptx
                path = "%s/bin:%s" % (self.installdir, os.getenv('PATH'))
                env.setvar('PATH', path)

                ld_lib_path = "%(dir)s/lib64:%(dir)s/lib:%(val)s" % {
                    'dir': self.installdir,
                    'val': os.getenv('LD_LIBRARY_PATH')
                }
                env.setvar('LD_LIBRARY_PATH', ld_lib_path)

                if self.current_stage == NVPTX_TOOLS:
                    # Configure NVPTX tools and build
                    change_dir(self.nvptx_tools_dir)
                    return super(EB_GCC, self).configure_step()

                elif self.current_stage == AMD_LLVM:
                    # determine LLVM target to use for host CPU
                    cpu_arch = get_cpu_architecture()
                    try:
                        llvm_target_cpu = LLVM_ARCH_MAP[cpu_arch][0]
                    except KeyError:
                        raise EasyBuildError("Failed to determine LLVM target for host CPU (%s)" % cpu_arch)

                    # Setup symlink from LLD source to 'builddir/lld' so that LLVM can find it
                    symlink(self.lld_dir, '%s/lld' % self.builddir)
                    # Build LLD tools from LLVM needed for AMD offloading
                    # Build LLVM in separate directory
                    self.create_dir('build_llvm_amdgcn')
                    cmd = ' '.join([
                        'cmake',
                        "-DLLVM_TARGETS_TO_BUILD='%s;AMDGPU'" % llvm_target_cpu,
                        "-DLLVM_ENABLE_PROJECTS=lld",
                        "-DCMAKE_BUILD_TYPE=Release",
                        self.llvm_dir,
                    ])
                    run_cmd(cmd, log_all=True, simple=True)
                    # Need to terminate the current configuration step, but we can't run 'configure' since LLVM uses
                    # CMake, we therefore run 'CMake' manually and then return nothing.
                    # The normal make stage will build LLVM for us as expected, note that we override the install step
                    # further down in this file to avoid installing LLVM
                    return

                elif self.current_stage in (AMD_NEWLIB, NVIDIA_NEWLIB):

                    symlink(os.path.join(self.newlib_dir, 'newlib'), 'newlib')
                    self.cfg.update('configopts', self.configopts)

                    if self.current_stage == NVIDIA_NEWLIB:
                        # compile nvptx target compiler
                        self.create_dir("build-nvptx-gcc")
                        target = 'nvptx-none'
                        self.cfg.update('configopts', "--enable-newlib-io-long-long")
                    else:
                        # compile AMD GCN target compiler
                        self.create_dir("build-amdgcn-gcc")
                        target = 'amdgcn-amdhsa'
                        self.cfg.update('configopts', "--with-newlib")
                        self.cfg.update('configopts', "--disable-libquadmath")

                    build_tools_dir = os.path.join(self.installdir, target, 'bin')
                    self.cfg.update('configopts', '--with-build-time-tools=' + build_tools_dir)
                    self.cfg.update('configopts', '--target=' + target)
                    host_type = self.determine_build_and_host_type()[1]
                    self.cfg.update('configopts', "--enable-as-accelerator-for=%s" % host_type)
                    self.cfg.update('configopts', "--disable-sjlj-exceptions")

                    self.cfg['configure_cmd_prefix'] = '../'
                    return super(EB_GCC, self).configure_step()

                else:
                    raise EasyBuildError("Unknown offload configure step: %s, available: %s"
                                         % (self.current_stage, self.build_stages))

        # enable building of libiberty, if desired
        if self.cfg['withlibiberty']:
            self.configopts += " --enable-install-libiberty"

        # enable link-time-optimization (LTO) support, if desired
        if self.cfg['withlto']:
            self.configopts += " --enable-lto"
        else:
            self.configopts += " --disable-lto"

        # configure for a release build
        self.configopts += " --enable-checking=release "
        # enable multilib: allow both 32 and 64 bit
        if self.cfg['multilib']:
            glibc_32bit = [
                "glibc.i686",  # Fedora, RedHat-based
                "glibc.ppc",   # "" on Power
                "libc6-dev-i386",  # Debian-based
                "gcc-c++-32bit",  # OpenSuSE, SLES
            ]
            if not any([check_os_dependency(dep) for dep in glibc_32bit]):
                raise EasyBuildError("Using multilib requires 32-bit glibc (install one of %s, depending on your OS)",
                                     ', '.join(glibc_32bit))
            self.configopts += " --enable-multilib --with-multilib-list=m32,m64"
        else:
            self.configopts += " --disable-multilib"
        # build both static and dynamic libraries (???)
        self.configopts += " --enable-shared=yes --enable-static=yes "

        # use POSIX threads
        self.configopts += " --enable-threads=posix "

        # enable plugin support
        self.configopts += " --enable-plugins "

        # use GOLD as default linker, except on RISC-V (since it's not supported there)
        if get_cpu_family() == RISCV:
            self.configopts += " --disable-gold --enable-ld=default"
        elif self.cfg['use_gold_linker']:
            self.configopts += " --enable-gold=default --enable-ld --with-plugin-ld=ld.gold"
        else:
            self.configopts += " --enable-gold --enable-ld=default"

        # enable bootstrap build for self-containment (unless for staged build)
        if not self.stagedbuild:
            configopts += " --enable-bootstrap"
        else:
            configopts += " --disable-bootstrap"

        if self.stagedbuild:
            #
            # STAGE 1: configure GCC build that will be used to build PPL/CLooG
            #
            self.log.info("Starting with stage 1 of 3-staged build to enable CLooG and/or PPL, ISL support...")
            self.stage1installdir = os.path.join(self.builddir, 'GCC_stage1_eb')
            configopts += " --prefix=%(p)s --with-local-prefix=%(p)s" % {'p': self.stage1installdir}

        else:
            # unstaged build, so just run standard configure/make/make install
            # set prefixes
            self.log.info("Performing regular GCC build...")
            configopts += " --prefix=%(p)s --with-local-prefix=%(p)s" % {'p': self.installdir}

        # prioritize lib over lib{64,32,x32} for all architectures by overriding default MULTILIB_OSDIRNAMES config
        # only do this when multilib is not enabled
        if self.cfg['prefer_lib_subdir'] and not self.cfg['multilib']:
            cfgfile = 'gcc/config/i386/t-linux64'
            multilib_osdirnames = "MULTILIB_OSDIRNAMES = m64=../lib:../lib64 m32=../lib:../lib32 mx32=../lib:../libx32"
            self.log.info("Patching MULTILIB_OSDIRNAMES in %s with '%s'", cfgfile, multilib_osdirnames)
            write_file(cfgfile, multilib_osdirnames, append=True)
        elif self.cfg['multilib']:
            self.log.info("Not patching MULTILIB_OSDIRNAMES since use of --enable-multilib is enabled")

        # III) create obj dir to build in, and change to it
        #     GCC doesn't like to be built in the source dir
        if self.stagedbuild:
            objdir = self.create_dir("stage1_obj")
            self.stage1prefix = objdir
        else:
            objdir = self.create_dir("obj")

        # IV) actual configure, but not on default path
        cmd = "../configure  %s %s" % (self.configopts, configopts)

        self.run_configure_cmd(cmd)

        self.disable_lto_mpfr_old_gcc(objdir)

    def build_step(self):
        """Custom (staged) build step for GCC."""

        if self.iter_idx > 0:
            # call standard build_step for nvptx-tools and nvptx GCC
            return super(EB_GCC, self).build_step()

        if self.stagedbuild:

            # make and install stage 1 build of GCC
            paracmd = ''
            if self.cfg['parallel']:
                paracmd = "-j %s" % self.cfg['parallel']

            cmd = "%s make %s %s" % (self.cfg['prebuildopts'], paracmd, self.cfg['buildopts'])
            run_cmd(cmd, log_all=True, simple=True)

            cmd = "make install %s" % (self.cfg['installopts'])
            run_cmd(cmd, log_all=True, simple=True)

            # register built GCC as compiler to use for stage 2/3
            path = "%s/bin:%s" % (self.stage1installdir, os.getenv('PATH'))
            env.setvar('PATH', path)

            ld_lib_path = "%(dir)s/lib64:%(dir)s/lib:%(val)s" % {
                'dir': self.stage1installdir,
                'val': os.getenv('LD_LIBRARY_PATH')
            }
            env.setvar('LD_LIBRARY_PATH', ld_lib_path)
            if get_cpu_family() == RISCV:
                # on RISC-V the compilers built in stage 1 fail to find some libraries from the lib dir,
                # so let's also set $LIBRARY_PATH to work around it
                env.setvar('LIBRARY_PATH', ld_lib_path)

            #
            # STAGE 2: build GMP/PPL/CLooG for stage 3
            #

            # create dir to build GMP/PPL/CLooG in
            stage2dir = "stage2_stuff"
            stage2prefix = self.create_dir(stage2dir)

            # prepare directories to build GMP/PPL/CLooG
            stage2_info = self.prep_extra_src_dirs("stage2", target_prefix=stage2prefix)
            configopts = stage2_info['configopts']

            # build PPL and CLooG (GMP as dependency)

            for lib in ["gmp"] + self.with_dirs:
                self.log.debug("Building %s in stage 2" % lib)
                if lib == "gmp" or self.cfg['with%s' % lib]:
                    libdir = os.path.join(stage2prefix, lib)
                    try:
                        os.chdir(libdir)
                    except OSError as err:
                        raise EasyBuildError("Failed to change to %s: %s", libdir, err)
                    if lib == "gmp":
                        cmd = "./configure --prefix=%s " % stage2prefix
                        cmd += "--with-pic --disable-shared --enable-cxx "

                        # ensure generic build when 'generic' is set to True or when --optarch=GENERIC is used
                        # non-generic build can be enforced with generic=False if --optarch=GENERIC is used
                        optarch_generic = build_option('optarch') == OPTARCH_GENERIC
                        if self.cfg['generic'] or (optarch_generic and self.cfg['generic'] is not False):
                            cmd += "--enable-fat "

                    elif lib == "ppl":
                        self.pplver = LooseVersion(stage2_info['versions']['ppl'])

                        cmd = "./configure --prefix=%s --with-pic -disable-shared " % stage2prefix
                        # only enable C/C++ interfaces (Java interface is sometimes troublesome)
                        cmd += "--enable-interfaces='c c++' "

                        # enable watchdog (or not)
                        if self.pplver <= LooseVersion("0.11"):
                            if self.cfg['pplwatchdog']:
                                cmd += "--enable-watchdog "
                            else:
                                cmd += "--disable-watchdog "
                        elif self.cfg['pplwatchdog']:
                            raise EasyBuildError("Enabling PPL watchdog only supported in PPL <= v0.11 .")

                        # make sure GMP we just built is found
                        cmd += "--with-gmp=%s " % stage2prefix
                    elif lib == "isl":
                        cmd = "./configure --prefix=%s --with-pic --disable-shared " % stage2prefix
                        cmd += "--with-gmp=system --with-gmp-prefix=%s " % stage2prefix

                        # ensure generic build when 'generic' is set to True or when --optarch=GENERIC is used
                        # non-generic build can be enforced with generic=False if --optarch=GENERIC is used
                        optarch_generic = build_option('optarch') == OPTARCH_GENERIC
                        if self.cfg['generic'] or (optarch_generic and self.cfg['generic'] is not False):
                            cmd += "--without-gcc-arch "

                    elif lib == "cloog":
                        self.cloogname = stage2_info['names']['cloog']
                        self.cloogver = LooseVersion(stage2_info['versions']['cloog'])
                        v0_15 = LooseVersion("0.15")
                        v0_16 = LooseVersion("0.16")

                        cmd = "./configure --prefix=%s --with-pic --disable-shared " % stage2prefix

                        # use ISL or PPL
                        if self.cfg['clooguseisl']:
                            if self.cfg['withisl']:
                                self.log.debug("Using external ISL for CLooG")
                                cmd += "--with-isl=system --with-isl-prefix=%s " % stage2prefix
                            elif self.cloogver >= v0_16:
                                self.log.debug("Using bundled ISL for CLooG")
                                cmd += "--with-isl=bundled "
                            else:
                                raise EasyBuildError("Using ISL is only supported in CLooG >= v0.16 (detected v%s).",
                                                     self.cloogver)
                        else:
                            if self.cloogname == "cloog-ppl" and self.cloogver >= v0_15 and self.cloogver < v0_16:
                                cmd += "--with-ppl=%s " % stage2prefix
                            else:
                                errormsg = "PPL only supported with CLooG-PPL v0.15.x (detected v%s)" % self.cloogver
                                errormsg += "\nNeither using PPL or ISL-based ClooG, I'm out of options..."
                                raise EasyBuildError(errormsg)

                        # make sure GMP is found
                        if self.cloogver >= v0_15 and self.cloogver < v0_16:
                            cmd += "--with-gmp=%s " % stage2prefix
                        elif self.cloogver >= v0_16:
                            cmd += "--with-gmp=system --with-gmp-prefix=%s " % stage2prefix
                        else:
                            raise EasyBuildError("Don't know how to specify location of GMP to configure of CLooG v%s.",
                                                 self.cloogver)
                    else:
                        raise EasyBuildError("Don't know how to configure for %s", lib)

                    # configure
                    self.run_configure_cmd(cmd)

                    # build and 'install'
                    cmd = "make %s" % paracmd
                    run_cmd(cmd, log_all=True, simple=True)

                    cmd = "make install"
                    run_cmd(cmd, log_all=True, simple=True)

                    if lib == "gmp":
                        # make sure correct GMP is found
                        libpath = os.path.join(stage2prefix, 'lib')

                        # fall back to lib64 directory if lib was not found,
                        # give up if neither are there
                        if not os.path.exists(libpath):
                            libpath += '64'
                        if not os.path.exists(libpath):
                            raise EasyBuildError("lib(64) subdirectory not found in %s!" % stage2prefix)

                        incpath = os.path.join(stage2prefix, 'include')

                        cppflags = os.getenv('CPPFLAGS', '')
                        env.setvar('CPPFLAGS', "%s -L%s -I%s " % (cppflags, libpath, incpath))

            #
            # STAGE 3: bootstrap build of final GCC (with PPL/CLooG support)
            #

            # create new obj dir and change into it
            self.create_dir("stage3_obj")

            # reconfigure for stage 3 build
            self.log.info("Stage 2 of 3-staged build completed, continuing with stage 3 "
                          "(with CLooG and/or PPL, ISL support enabled)...")

            stage3_info = self.prep_extra_src_dirs("stage3")
            configopts = stage3_info['configopts']
            configopts += " --prefix=%(p)s --with-local-prefix=%(p)s" % {'p': self.installdir}

            # enable bootstrapping for self-containment
            configopts += " --enable-bootstrap "

            # PPL config options
            if self.cfg['withppl']:
                # for PPL build and CLooG-PPL linking
                for lib in ["lib64", "lib"]:
                    path = os.path.join(self.stage1installdir, lib, "libstdc++.a")
                    if os.path.exists(path):
                        libstdcxxpath = path
                        break
                configopts += "--with-host-libstdcxx='-static-libgcc %s -lm' " % libstdcxxpath

                configopts += "--with-ppl=%s " % stage2prefix

                if self.pplver <= LooseVersion("0.11"):
                    if self.cfg['pplwatchdog']:
                        configopts += "--enable-watchdog "
                    else:
                        configopts += "--disable-watchdog "

            # CLooG config options
            if self.cfg['withcloog']:
                configopts += "--with-cloog=%s " % stage2prefix

                gccver = LooseVersion(self.version)
                if self.cfg['clooguseisl'] and self.cloogver >= LooseVersion('0.16') and gccver < LooseVersion('4.8.0'):
                    configopts += "--enable-cloog-backend=isl "

            if self.cfg['withisl']:
                configopts += "--with-isl=%s " % stage2prefix

            # configure
            cmd = "../configure %s %s" % (self.configopts, configopts)
            self.run_configure_cmd(cmd)

        # build with bootstrapping for self-containment
        if self.cfg['profiled']:
            self.cfg.update('buildopts', 'profiledbootstrap')
        else:
            self.cfg.update('buildopts', 'bootstrap')

        # call standard build_step
        super(EB_GCC, self).build_step()

    def install_step(self, *args, **kwargs):
        """Custom install step: avoid installing LLVM when building with AMD GCN offloading support"""
        # When building AMD offloading do not install the LLVM source files with 'make install', instead move a few
        # binaries that GCC expects when building 'newlib' so that it can reuse the LLVM GCN support
        # https://gcc.gnu.org/wiki/Offloading#For_AMD_GCN:
        if self.current_stage == AMD_LLVM:
            llvm_binaries = [
                ('ar', 'llvm-ar'),
                ('as', 'llvm-mc'),
                ('ld', 'lld'),
                ('nm', 'llvm-nm'),
                ('ranlib', 'llvm-ar'),
            ]
            hits = glob.glob(os.path.join(self.builddir, 'gcc-*'))
            if len(hits) == 1:
                gcc_build_dir = hits[0]
                for gcc_tool, llvm_tool in llvm_binaries:
                    from_path = os.path.join(gcc_build_dir, 'build_llvm_amdgcn', 'bin', llvm_tool)
                    to_path = os.path.join(self.installdir, 'amdgcn-amdhsa', 'bin', gcc_tool)
                    copy_file(from_path, to_path)
            else:
                raise EasyBuildError("Failed to isolate GCC build directory in %s", self.builddir)

        else:
            super(EB_GCC, self).install_step(*args, **kwargs)

    def post_install_step(self, *args, **kwargs):
        """
        Post-processing after installation: add symlinks for cc, c++, f77, f95
        """
        super(EB_GCC, self).post_install_step(*args, **kwargs)

        # Add symlinks for cc/c++/f77/f95.
        bindir = os.path.join(self.installdir, 'bin')
        for key in COMP_CMD_SYMLINKS:
            src = COMP_CMD_SYMLINKS[key]
            target = os.path.join(bindir, key)
            if os.path.exists(target):
                self.log.info("'%s' already exists in %s, not replacing it with symlink to '%s'",
                              key, bindir, src)
            elif os.path.exists(os.path.join(bindir, src)):
                symlink(src, target, use_abspath_source=False)
            else:
                raise EasyBuildError("Can't link '%s' to non-existing location %s", target, os.path.join(bindir, src))

        # The include-fixed directory includes system header files that were processed by fixincludes.
        # These may cause problems when upgrading to newer OS version,
        # see https://github.com/easybuilders/easybuild-easyconfigs/issues/10666
        glob_pattern = os.path.join(self.installdir, 'lib*', 'gcc', '*-linux-gnu', self.version, 'include-fixed')
        paths = glob.glob(glob_pattern)
        if paths:
            # weed out paths that point to the same location,
            # for example when 'lib64' is a symlink to 'lib'
            include_fixed_paths = []
            for path in paths:
                if not any(os.path.samefile(path, x) for x in include_fixed_paths):
                    include_fixed_paths.append(path)

            if len(include_fixed_paths) != 1:
                raise EasyBuildError("Exactly one 'include-fixed' directory expected, found %d: %s",
                                     len(include_fixed_paths), include_fixed_paths)
            include_fixed_path = include_fixed_paths[0]

            if self.cfg['rename_include_fixed']:
                self.log.info("Found include-fixed subdirectory at %s", include_fixed_path)
                include_fixed_renamed = include_fixed_path + '.renamed-by-easybuild'
                move_file(include_fixed_path, include_fixed_renamed)
                self.log.info("%s renamed to %s to avoid using the header files in it",
                              include_fixed_path, include_fixed_renamed)
                # We need to retain some files, e.g. syslimits.h is required by /usr/include/limits.h
                mkdir(include_fixed_path)
                retained_header_files = ['limits.h', 'syslimits.h']
                for fn in retained_header_files:
                    from_path = os.path.join(include_fixed_renamed, fn)
                    to_path = os.path.join(include_fixed_path, fn)
                    if os.path.exists(from_path):
                        copy_file(from_path, to_path)
                        self.log.info("%s copied to %s after renaming %s", from_path, to_path, include_fixed_path)
                    else:
                        self.log.warning("Can't copy non-existing file %s to %s, since it doesn't exist!",
                                         from_path, to_path)

                readme = os.path.join(include_fixed_path, 'README.easybuild')
                readme_txt = '\n'.join([
                    "This directory was renamed by EasyBuild to avoid that the header files in it are picked up,",
                    "since they may cause problems when the OS is upgraded to a new (minor) version.",
                    '',
                    "These files were copied to %s first: %s" % (include_fixed_path, ', '.join(retained_header_files)),
                    '',
                    "See https://github.com/easybuilders/easybuild-easyconfigs/issues/10666 for more information.",
                    '',
                ])
                write_file(readme, readme_txt)

            # If the mkheaders utility exists we create a wrapper script to (re)generate the fixed headers manually,
            # e.g. after OS upgrades.
            # Get the '*-linux-gnu' part
            target_machine = os.path.basename(os.path.dirname(os.path.dirname(include_fixed_path)))
            mkheaders_path = os.path.join(self.installdir, 'libexec', 'gcc', target_machine, self.version,
                                          'install-tools', 'mkheaders')
            if os.path.isfile(mkheaders_path):
                recreate_include_fixed_script = os.path.join(self.installdir, 'easybuild', 'recreate_includes.sh')
                self.log.info("Creating script to regenerate %s on OS upgrades at %s",
                              include_fixed_path, recreate_include_fixed_script)
                relative_mkheaders = os.path.relpath(mkheaders_path, self.installdir)
                relative_include_fixed = os.path.relpath(include_fixed_path, self.installdir)
                write_file(recreate_include_fixed_script, RECREATE_INCLUDE_FIXED_SCRIPT_TMPL % {
                    "relative_mkheaders": relative_mkheaders,
                    "relative_include_fixed": relative_include_fixed
                })
                adjust_permissions(recreate_include_fixed_script, stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH, add=True)
        else:
            self.log.info("No include-fixed subdirectory found at %s", glob_pattern)

    def run_all_steps(self, *args, **kwargs):
        """
        If 'withnvptx' or 'withamdgcn' is set, use iterated build:
        iteration 0 builds the regular host compiler
        iteration 1 builds nvptx-tools
        iteration 2 builds the nvptx target compiler
        iteration 3 builds LLD for AMD GCN offloading
        iteration 4 builds the AMD GCN target compiler using LLD from above
        """
        self.cfg['configopts'] = ['']
        self.cfg['buildopts'] = ['']
        if self.cfg['withnvptx']:
            # Add two additional configure and build stages when enabling NVPTX
            # this is required to first build NVPTX tools and then newlib
            self.cfg['configopts'] += ['', '']
            self.cfg['buildopts'] += ['', '']
            self.build_stages.append(NVPTX_TOOLS)
            self.build_stages.append(NVIDIA_NEWLIB)
        if self.cfg['withamdgcn']:
            # Add two additional stages when enabling AMD GCN
            # this is required to first build LLVM tools and then newlib
            self.cfg['configopts'] += ['', '']
            self.cfg['buildopts'] += ['', '']
            self.build_stages.append(AMD_LLVM)
            self.build_stages.append(AMD_NEWLIB)
        return super(EB_GCC, self).run_all_steps(*args, **kwargs)

    def sanity_check_step(self):
        """
        Custom sanity check for GCC
        """

        os_type = get_os_type()
        sharedlib_ext = get_shared_lib_ext()

        # determine "configuration name" directory, see https://sourceware.org/autobook/autobook/autobook_17.html
        # this differs across GCC versions;
        # x86_64-unknown-linux-gnu was common for old GCC versions,
        # x86_64-pc-linux-gnu is more likely with an updated config.guess script;
        # since this is internal to GCC, we don't really care how it is named exactly,
        # we only care that it's actually there

        # we may get multiple hits (libexec/, lib/), which is fine,
        # but we expect the same configuration name subdirectory in each of them
        glob_pattern = os.path.join(self.installdir, 'lib*', 'gcc', '*-linux-gnu', self.version)
        matches = glob.glob(glob_pattern)
        if matches:
            cands = nub([os.path.basename(os.path.dirname(x)) for x in matches])
            if len(cands) == 1:
                config_name_subdir = cands[0]
            else:
                raise EasyBuildError("Found multiple candidates for configuration name: %s", ', '.join(cands))
        else:
            raise EasyBuildError("Failed to determine configuration name: no matches for '%s'", glob_pattern)

        bin_files = ["gcov"]
        lib_files = []
        if LooseVersion(self.version) >= LooseVersion('4.2'):
            # libgomp was added in GCC 4.2.0
            ["libgomp.%s" % sharedlib_ext, "libgomp.a"]
        if os_type == 'Linux':
            lib_files.extend(["libgcc_s.%s" % sharedlib_ext])
            # libmudflap is replaced by asan (see release notes gcc 4.9.0)
            if LooseVersion(self.version) < LooseVersion("4.9.0"):
                lib_files.extend(["libmudflap.%s" % sharedlib_ext, "libmudflap.a"])
            else:
                lib_files.extend(["libasan.%s" % sharedlib_ext, "libasan.a"])
        libexec_files = []
        dirs = [os.path.join('lib', 'gcc', config_name_subdir, self.version)]

        languages = self.cfg['languages'] or ['c', 'c++', 'fortran']  # default languages

        if 'c' in languages:
            bin_files.extend(['cpp', 'gcc'])
            libexec_files.extend(['cc1', 'collect2'])

        if 'c++' in languages:
            bin_files.extend(['c++', 'g++'])
            dirs.append('include/c++/%s' % self.version)
            lib_files.extend(["libstdc++.%s" % sharedlib_ext, "libstdc++.a"])
            libexec_files.append('cc1plus')  # c++ requires c, so collect2 not mentioned again

        if 'fortran' in languages:
            bin_files.append('gfortran')
            lib_files.extend(['libgfortran.%s' % sharedlib_ext, 'libgfortran.a'])
            libexec_files.append('f951')

        if self.cfg['withlto']:
            libexec_files.extend(['lto1', 'lto-wrapper'])
            if os_type in ['Linux']:
                libexec_files.append('liblto_plugin.%s' % sharedlib_ext)

        if self.cfg['withnvptx']:
            bin_files.extend(['nvptx-none-as', 'nvptx-none-ld'])
            lib_files.append('libgomp-plugin-nvptx.%s' % sharedlib_ext)

        if self.cfg['withamdgcn']:
            lib_files.append('libgomp-plugin-gcn.%s' % sharedlib_ext)

        bin_files = ["bin/%s" % x for x in bin_files]
        libdirs64 = ['lib64']
        libdirs32 = ['lib', 'lib32']
        libdirs = libdirs64 + libdirs32
        if self.cfg['multilib']:
            # with multilib enabled, both lib and lib64 should be there
            lib_files64 = [os.path.join(libdir, x) for libdir in libdirs64 for x in lib_files]
            lib_files32 = [tuple([os.path.join(libdir, x) for libdir in libdirs32]) for x in lib_files]
            lib_files = lib_files64 + lib_files32
        else:
            # lib64 on SuSE and Darwin, lib otherwise
            lib_files = [tuple([os.path.join(libdir, x) for libdir in libdirs]) for x in lib_files]
        # lib on SuSE, libexec otherwise
        libdirs = ['libexec', 'lib']
        common_infix = os.path.join('gcc', config_name_subdir, self.version)
        libexec_files = [tuple([os.path.join(d, common_infix, x) for d in libdirs]) for x in libexec_files]

        old_cmds = [os.path.join('bin', x) for x in COMP_CMD_SYMLINKS.keys()]

        custom_paths = {
            'files': bin_files + lib_files + libexec_files + old_cmds,
            'dirs': dirs,
        }

        custom_commands = []
        for lang, compiler in (('c', 'gcc'), ('c++', 'g++')):
            if lang in languages:
                # Simple test compile
                cmd = 'echo "int main(){} " | %s -x %s -o/dev/null -'
                compiler_path = os.path.join(self.installdir, 'bin', compiler)
                custom_commands.append(cmd % (compiler_path, lang))
                if self.cfg['withlto']:
                    custom_commands.append(cmd % (compiler_path, lang + ' -flto -fuse-linker-plugin'))
        if custom_commands:
            # Load binutils to do the compile tests
            extra_modules = [d['short_mod_name'] for d in self.cfg.dependencies() if d['name'] == 'binutils']
        else:
            extra_modules = None

        super(EB_GCC, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands,
                                              extra_modules=extra_modules)

    def make_module_req_guess(self):
        """
        GCC can find its own headers and libraries but the .so's need to be in LD_LIBRARY_PATH
        """
        guesses = super(EB_GCC, self).make_module_req_guess()
        guesses.update({
            'PATH': ['bin'],
            'CPATH': [],
            'LIBRARY_PATH': ['lib', 'lib64'] if get_cpu_family() == RISCV else [],
            'LD_LIBRARY_PATH': ['lib', 'lib64'],
            'MANPATH': ['man', 'share/man']
        })
        return guesses
