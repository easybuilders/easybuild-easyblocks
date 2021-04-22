##
# Copyright 2009-2021 Ghent University
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
EasyBuild support for building and installing OpenFOAM, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Xavier Besseron (University of Luxembourg)
@author: Ward Poelmans (Ghent University)
@author: Balazs Hajgato (Free University Brussels (VUB))
"""

import glob
import os
import re
import shutil
import stat
from distutils.version import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.cmakemake import setup_cmake_env
from easybuild.framework.easyblock import EasyBlock
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, mkdir
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd, run_cmd_qa
from easybuild.tools.systemtools import get_shared_lib_ext, get_cpu_architecture, AARCH64, POWER


class EB_OpenFOAM(EasyBlock):
    """Support for building and installing OpenFOAM."""

    def __init__(self, *args, **kwargs):
        """Specify that OpenFOAM should be built in install dir."""

        super(EB_OpenFOAM, self).__init__(*args, **kwargs)

        self.build_in_installdir = True

        self.wm_compiler = None
        self.wm_mplib = None
        self.openfoamdir = None
        self.thrdpartydir = None

        # version may start with 'v' for some variants of OpenFOAM
        # we need to strip this off to avoid problems when comparing LooseVersion instances in Python 3
        clean_version = self.version.strip('v+')

        # take into account versions like '4.x',
        # assume it's equivalent to a very recent minor version (.99)
        if '.x' in clean_version:
            clean_version = clean_version.replace('.x', '.99')

        self.looseversion = LooseVersion(clean_version)

        if 'extend' in self.name.lower():
            if self.looseversion >= LooseVersion('3.0'):
                self.openfoamdir = 'foam-extend-%s' % self.version
            else:
                self.openfoamdir = 'OpenFOAM-%s-ext' % self.version
        else:
            self.openfoamdir = '-'.join([self.name, '-'.join(self.version.split('-')[:2])])
        self.log.debug("openfoamdir: %s" % self.openfoamdir)

        # Set build type to requested value
        if self.toolchain.options['debug']:
            self.build_type = 'Debug'
        else:
            self.build_type = 'Opt'

    def extract_step(self):
        """Extract sources as expected by the OpenFOAM(-Extend) build scripts."""
        super(EB_OpenFOAM, self).extract_step()
        # make sure that the expected subdir is really there after extracting
        # if not, the build scripts (e.g., the etc/bashrc being sourced) will likely fail
        openfoam_installdir = os.path.join(self.installdir, self.openfoamdir)
        if not os.path.exists(openfoam_installdir):
            self.log.warning("Creating expected directory %s, and moving everything there" % openfoam_installdir)
            try:
                contents_installdir = os.listdir(self.installdir)
                source = os.path.join(self.installdir, contents_installdir[0])
                # it's one directory but has a wrong name
                if len(contents_installdir) == 1 and os.path.isdir(source):
                    target = os.path.join(self.installdir, self.openfoamdir)
                    self.log.debug("Renaming %s to %s", source, target)
                    os.rename(source, target)
                else:
                    mkdir(openfoam_installdir)
                    for fil in contents_installdir:
                        if fil != self.openfoamdir:
                            source = os.path.join(self.installdir, fil)
                            target = os.path.join(openfoam_installdir, fil)
                            self.log.debug("Moving %s to %s", source, target)
                            shutil.move(source, target)
                    os.chdir(openfoam_installdir)
            except OSError as err:
                raise EasyBuildError("Failed to move all files to %s: %s", openfoam_installdir, err)

    def patch_step(self, beginpath=None):
        """Adjust start directory and start path for patching to correct directory."""
        self.cfg['start_dir'] = os.path.join(self.installdir, self.openfoamdir)
        super(EB_OpenFOAM, self).patch_step(beginpath=self.cfg['start_dir'])

    def prepare_step(self, *args, **kwargs):
        """Prepare for OpenFOAM install procedure."""
        super(EB_OpenFOAM, self).prepare_step(*args, **kwargs)

        comp_fam = self.toolchain.comp_family()
        if comp_fam == toolchain.GCC:  # @UndefinedVariable
            self.wm_compiler = 'Gcc'
        elif comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
            self.wm_compiler = 'Icc'
        else:
            raise EasyBuildError("Unknown compiler family, don't know how to set WM_COMPILER")

        # set to an MPI unknown by OpenFOAM, since we're handling the MPI settings ourselves (via mpicc, etc.)
        # Note: this name must contain 'MPI' so the MPI version of the
        # Pstream library is built (cf src/Pstream/Allwmake)
        self.wm_mplib = "EASYBUILDMPI"

    def configure_step(self):
        """Configure OpenFOAM build by setting appropriate environment variables."""
        # compiler & compiler flags
        comp_fam = self.toolchain.comp_family()

        extra_flags = ''
        if comp_fam == toolchain.GCC:  # @UndefinedVariable
            if get_software_version('GCC') >= LooseVersion('4.8'):
                # make sure non-gold version of ld is used, since OpenFOAM requires it
                # see http://www.openfoam.org/mantisbt/view.php?id=685
                extra_flags = '-fuse-ld=bfd'

            # older versions of OpenFOAM-Extend require -fpermissive
            if 'extend' in self.name.lower() and self.looseversion < LooseVersion('2.0'):
                extra_flags += ' -fpermissive'

            if self.looseversion < LooseVersion('3.0'):
                extra_flags += ' -fno-delete-null-pointer-checks'

        elif comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
            # make sure -no-prec-div is used with Intel compilers
            extra_flags = '-no-prec-div'

        for env_var in ['CFLAGS', 'CXXFLAGS']:
            env.setvar(env_var, "%s %s" % (os.environ.get(env_var, ''), extra_flags))

        # patch out hardcoding of WM_* environment variables
        # for example, replace 'export WM_COMPILER=Gcc' with ': ${WM_COMPILER:=Gcc}; export WM_COMPILER'
        for script in [os.path.join(self.builddir, self.openfoamdir, x) for x in ['etc/bashrc', 'etc/cshrc']]:
            self.log.debug("Patching out hardcoded $WM_* env vars in %s", script)
            # disable any third party stuff, we use EB controlled builds
            regex_subs = [(r"^(setenv|export) WM_THIRD_PARTY_USE_.*[ =].*$", r"# \g<0>")]

            # this does not work for OpenFOAM Extend lower than 2.0
            if 'extend' not in self.name.lower() or self.looseversion >= LooseVersion('2.0'):
                key = "WM_PROJECT_VERSION"
                regex_subs += [(r"^(setenv|export) %s=.*$" % key, r"export %s=%s #\g<0>" % (key, self.version))]

            WM_env_var = ['WM_COMPILER', 'WM_COMPILE_OPTION', 'WM_MPLIB', 'WM_THIRD_PARTY_DIR']
            # OpenFOAM >= 3.0.0 can use 64 bit integers
            if 'extend' not in self.name.lower() and self.looseversion >= LooseVersion('3.0'):
                WM_env_var.append('WM_LABEL_SIZE')
            for env_var in WM_env_var:
                regex_subs.append((r"^(setenv|export) (?P<var>%s)[ =](?P<val>.*)$" % env_var,
                                   r": ${\g<var>:=\g<val>}; export \g<var>"))
            apply_regex_substitutions(script, regex_subs)

        # inject compiler variables into wmake/rules files
        ldirs = glob.glob(os.path.join(self.builddir, self.openfoamdir, 'wmake', 'rules', 'linux*'))
        if self.looseversion >= LooseVersion('1906'):
            ldirs += glob.glob(os.path.join(self.builddir, self.openfoamdir, 'wmake', 'rules', 'General', '*'))
        langs = ['c', 'c++']

        # NOTE: we do not want to change the Debug rules files becuse
        # that would change the cOPT/c++OPT values from their empty setting.
        suffixes = ['', 'Opt']
        wmake_rules_files = [os.path.join(ldir, lang + suff) for ldir in ldirs for lang in langs for suff in suffixes]

        mpicc = os.environ['MPICC']
        mpicxx = os.environ['MPICXX']
        cc_seq = os.environ.get('CC_SEQ', os.environ['CC'])
        cxx_seq = os.environ.get('CXX_SEQ', os.environ['CXX'])

        if self.toolchain.mpi_family() == toolchain.OPENMPI:
            # no -cc/-cxx flags supported in OpenMPI compiler wrappers
            c_comp_cmd = 'OMPI_CC="%s" %s' % (cc_seq, mpicc)
            cxx_comp_cmd = 'OMPI_CXX="%s" %s' % (cxx_seq, mpicxx)
        else:
            # -cc/-cxx should work for all MPICH-based MPIs (including Intel MPI)
            c_comp_cmd = '%s -cc="%s"' % (mpicc, cc_seq)
            cxx_comp_cmd = '%s -cxx="%s"' % (mpicxx, cxx_seq)

        comp_vars = {
            # specify MPI compiler wrappers and compiler commands + sequential compiler that should be used by them
            'cc': c_comp_cmd,
            'CC': cxx_comp_cmd,
            'cOPT': os.environ['CFLAGS'],
            'c++OPT': os.environ['CXXFLAGS'],
        }
        for wmake_rules_file in wmake_rules_files:
            # the cOpt and c++Opt files don't exist in the General directories (which are included for recent versions)
            if not os.path.isfile(wmake_rules_file):
                continue
            fullpath = os.path.join(self.builddir, self.openfoamdir, wmake_rules_file)
            self.log.debug("Patching compiler variables in %s", fullpath)
            regex_subs = []
            for comp_var, newval in comp_vars.items():
                regex_subs.append((r"^(%s\s*=\s*).*$" % re.escape(comp_var), r"\1%s" % newval))
            apply_regex_substitutions(fullpath, regex_subs)

        # enable verbose build for debug purposes
        # starting with openfoam-extend 3.2, PS1 also needs to be set
        env.setvar("FOAM_VERBOSE", '1')

        # installation directory
        env.setvar("FOAM_INST_DIR", self.installdir)

        # third party directory
        self.thrdpartydir = "ThirdParty-%s" % self.version
        # only if third party stuff is actually installed
        if os.path.exists(self.thrdpartydir):
            os.symlink(os.path.join("..", self.thrdpartydir), self.thrdpartydir)
            env.setvar("WM_THIRD_PARTY_DIR", os.path.join(self.installdir, self.thrdpartydir))

        env.setvar("WM_COMPILER", self.wm_compiler)
        env.setvar("WM_MPLIB", self.wm_mplib)

        # Set Compile options according to build type
        env.setvar("WM_COMPILE_OPTION", self.build_type)

        # parallel build spec
        env.setvar("WM_NCOMPPROCS", str(self.cfg['parallel']))

        # OpenFOAM >= 3.0.0 can use 64 bit integers
        if 'extend' not in self.name.lower() and self.looseversion >= LooseVersion('3.0'):
            if self.toolchain.options['i8']:
                env.setvar("WM_LABEL_SIZE", '64')
            else:
                env.setvar("WM_LABEL_SIZE", '32')

        # make sure lib/include dirs for dependencies are found
        openfoam_extend_v3 = 'extend' in self.name.lower() and self.looseversion >= LooseVersion('3.0')
        if self.looseversion < LooseVersion("2") or openfoam_extend_v3:
            self.log.debug("List of deps: %s" % self.cfg.dependencies())
            for dep in self.cfg.dependencies():
                dep_name = dep['name'].upper(),
                dep_root = get_software_root(dep['name'])
                env.setvar("%s_SYSTEM" % dep_name, "1")
                dep_vars = {
                    "%s_DIR": "%s",
                    "%s_BIN_DIR": "%s/bin",
                    "%s_LIB_DIR": "%s/lib",
                    "%s_INCLUDE_DIR": "%s/include",
                }
                for var, val in dep_vars.items():
                    env.setvar(var % dep_name, val % dep_root)
        else:
            for depend in ['SCOTCH', 'METIS', 'CGAL', 'Paraview']:
                dependloc = get_software_root(depend)
                if dependloc:
                    if depend == 'CGAL' and get_software_root('Boost'):
                        env.setvar("CGAL_ROOT", dependloc)
                        env.setvar("BOOST_ROOT", get_software_root('Boost'))
                    else:
                        env.setvar("%s_ROOT" % depend.upper(), dependloc)

    def build_step(self):
        """Build OpenFOAM using make after sourcing script to set environment."""

        # Some parts of OpenFOAM uses CMake to build
        # make sure the basic environment is correct
        setup_cmake_env(self.toolchain)

        precmd = "source %s" % os.path.join(self.builddir, self.openfoamdir, "etc", "bashrc")
        if 'extend' not in self.name.lower() and self.looseversion >= LooseVersion('4.0'):
            if self.looseversion >= LooseVersion('2006'):
                cleancmd = "cd $WM_PROJECT_DIR && wclean -platform -all && cd -"
            else:
                cleancmd = "cd $WM_PROJECT_DIR && wcleanPlatform -all && cd -"
        else:
            cleancmd = "wcleanAll"

        # make directly in install directory
        cmd_tmpl = "%(precmd)s && %(cleancmd)s && %(prebuildopts)s %(makecmd)s" % {
            'precmd': precmd,
            'cleancmd': cleancmd,
            'prebuildopts': self.cfg['prebuildopts'],
            'makecmd': os.path.join(self.builddir, self.openfoamdir, '%s'),
        }
        if 'extend' in self.name.lower() and self.looseversion >= LooseVersion('3.0'):
            qa = {
                "Proceed without compiling ParaView [Y/n]": 'Y',
                "Proceed without compiling cudaSolvers? [Y/n]": 'Y',
            }
            noqa = [
                ".* -o .*",
                "checking .*",
                "warning.*",
                "configure: creating.*",
                "%s .*" % os.environ['CC'],
                "wmake .*",
                "Making dependency list for source file.*",
                r"\s*\^\s*",  # warning indicator
                "Cleaning .*",
            ]
            run_cmd_qa(cmd_tmpl % 'Allwmake.firstInstall', qa, no_qa=noqa, log_all=True, simple=True, maxhits=500)
        else:
            cmd = 'Allwmake'
            if self.looseversion > LooseVersion('1606'):
                # use Allwmake -log option if possible since this can be useful during builds, but also afterwards
                cmd += ' -log'
            run_cmd(cmd_tmpl % cmd, log_all=True, simple=True, log_output=True)

    def det_psubdir(self):
        """Determine the platform-specific installation directory for OpenFOAM."""
        # OpenFOAM >= 3.0.0 can use 64 bit integers
        # same goes for OpenFOAM-Extend >= 4.1
        if 'extend' in self.name.lower():
            set_int_size = self.looseversion >= LooseVersion('4.1')
        else:
            set_int_size = self.looseversion >= LooseVersion('3.0')

        if set_int_size:
            if self.toolchain.options['i8']:
                int_size = 'Int64'
            else:
                int_size = 'Int32'
        else:
            int_size = ''

        archpart = '64'
        arch = get_cpu_architecture()
        if arch == AARCH64:
            # Variants have different abbreviations for ARM64...
            if self.looseversion < LooseVersion("100"):
                archpart = 'Arm64'
            else:
                archpart = 'ARM64'
        elif arch == POWER:
            archpart = 'PPC64le'

        psubdir = "linux%s%sDP%s%s" % (archpart, self.wm_compiler, int_size, self.build_type)
        return psubdir

    def install_step(self):
        """Building was performed in install dir, so just fix permissions."""

        # fix permissions of OpenFOAM dir
        fullpath = os.path.join(self.installdir, self.openfoamdir)
        adjust_permissions(fullpath, stat.S_IROTH, add=True, recursive=True, ignore_errors=True)
        adjust_permissions(fullpath, stat.S_IXOTH, add=True, recursive=True, onlydirs=True, ignore_errors=True)

        # fix permissions of ThirdParty dir and subdirs (also for 2.x)
        # if the thirdparty tarball is installed
        fullpath = os.path.join(self.installdir, self.thrdpartydir)
        if os.path.exists(fullpath):
            adjust_permissions(fullpath, stat.S_IROTH, add=True, recursive=True, ignore_errors=True)
            adjust_permissions(fullpath, stat.S_IXOTH, add=True, recursive=True, onlydirs=True, ignore_errors=True)

        # create symlinks in the lib directory to all libraries in the mpi subdirectory
        # to make sure they take precedence over the libraries in the dummy subdirectory
        shlib_ext = get_shared_lib_ext()
        psubdir = self.det_psubdir()
        openfoam_extend_v3 = 'extend' in self.name.lower() and self.looseversion >= LooseVersion('3.0')
        if openfoam_extend_v3 or self.looseversion < LooseVersion("2"):
            libdir = os.path.join(self.installdir, self.openfoamdir, "lib", psubdir)
        else:
            libdir = os.path.join(self.installdir, self.openfoamdir, "platforms", psubdir, "lib")

        # OpenFOAM v2012 puts mpi into eb-mpi
        if self.looseversion >= LooseVersion("2012"):
            mpilibssubdir = "eb-mpi"
        else:
            mpilibssubdir = "mpi"
        mpilibsdir = os.path.join(libdir, mpilibssubdir)

        if os.path.exists(mpilibsdir):
            for lib in glob.glob(os.path.join(mpilibsdir, "*.%s" % shlib_ext)):
                libname = os.path.basename(lib)
                dst = os.path.join(libdir, libname)
                os.symlink(os.path.join(mpilibssubdir, libname), dst)

    def sanity_check_step(self):
        """Custom sanity check for OpenFOAM"""
        shlib_ext = get_shared_lib_ext()
        psubdir = self.det_psubdir()

        openfoam_extend_v3 = 'extend' in self.name.lower() and self.looseversion >= LooseVersion('3.0')
        if openfoam_extend_v3 or self.looseversion < LooseVersion("2"):
            toolsdir = os.path.join(self.openfoamdir, "applications", "bin", psubdir)
            libsdir = os.path.join(self.openfoamdir, "lib", psubdir)
            dirs = [toolsdir, libsdir]
        else:
            toolsdir = os.path.join(self.openfoamdir, "platforms", psubdir, "bin")
            libsdir = os.path.join(self.openfoamdir, "platforms", psubdir, "lib")
            dirs = [toolsdir, libsdir]

        # some randomly selected binaries
        # if one of these is missing, it's very likely something went wrong
        bins = [os.path.join(self.openfoamdir, "bin", x) for x in ["paraFoam"]] + \
               [os.path.join(toolsdir, "buoyantSimpleFoam")] + \
               [os.path.join(toolsdir, "%sFoam" % x) for x in ["boundary", "engine"]] + \
               [os.path.join(toolsdir, "surface%s" % x) for x in ["Add", "Find", "Smooth"]] + \
               [os.path.join(toolsdir, x) for x in ['blockMesh', 'checkMesh', 'deformedGeom', 'engineSwirl',
                                                    'modifyMesh', 'refineMesh']]

        # test setting up the OpenFOAM environment in bash shell
        load_openfoam_env = "source $FOAM_BASH"
        custom_commands = [load_openfoam_env]

        # only include Boussinesq and sonic since for OpenFOAM < 7, since those solvers have been deprecated
        if self.looseversion < LooseVersion('7'):
            bins.extend([
                os.path.join(toolsdir, "buoyantBoussinesqSimpleFoam"),
                os.path.join(toolsdir, "sonicFoam")
            ])

        # check for the Pstream and scotchDecomp libraries, there must be a dummy one and an mpi one
        if 'extend' in self.name.lower():
            libs = [os.path.join(libsdir, "libscotchDecomp.%s" % shlib_ext),
                    os.path.join(libsdir, "libmetisDecomp.%s" % shlib_ext)]
            if self.looseversion < LooseVersion('3.2'):
                # Pstream should have both a dummy and a mpi one
                libs.extend([os.path.join(libsdir, x, "libPstream.%s" % shlib_ext) for x in ["dummy", "mpi"]])
                libs.extend([os.path.join(libsdir, "mpi", "libparMetisDecomp.%s" % shlib_ext)])
            else:
                libs.extend([os.path.join(libsdir, "libparMetisDecomp.%s" % shlib_ext)])
        else:
            # OpenFOAM v2012 puts mpi into eb-mpi
            if self.looseversion >= LooseVersion("2012"):
                mpilibssubdir = "eb-mpi"
            else:
                mpilibssubdir = "mpi"

            # there must be a dummy one and an mpi one for both
            libs = [os.path.join(libsdir, x, "libPstream.%s" % shlib_ext) for x in ["dummy", mpilibssubdir]] + \
                   [os.path.join(libsdir, x, "libptscotchDecomp.%s" % shlib_ext) for x in ["dummy", mpilibssubdir]] +\
                   [os.path.join(libsdir, "libscotchDecomp.%s" % shlib_ext)] + \
                   [os.path.join(libsdir, "dummy", "libscotchDecomp.%s" % shlib_ext)]

        if 'extend' not in self.name.lower() and self.looseversion >= LooseVersion("2.3.0"):
            # surfaceSmooth is replaced by surfaceLambdaMuSmooth is OpenFOAM v2.3.0
            bins.remove(os.path.join(toolsdir, "surfaceSmooth"))
            bins.append(os.path.join(toolsdir, "surfaceLambdaMuSmooth"))

        if 'extend' not in self.name.lower() and self.looseversion >= LooseVersion("2.4.0"):
            # also check for foamMonitor for OpenFOAM versions other than OpenFOAM-Extend
            bins.append(os.path.join(self.openfoamdir, 'bin', 'foamMonitor'))

            # test foamMonitor; wrap `foamMonitor -h` to generate exit code 1 if any dependency is missing
            # the command `foamMonitor -h` does not return correct exit codes on its own in all versions
            test_foammonitor = "! foamMonitor -h 2>&1 | grep 'not installed'"
            custom_commands.append(' && '.join([load_openfoam_env, test_foammonitor]))

        custom_paths = {
            'files': [os.path.join(self.openfoamdir, 'etc', x) for x in ["bashrc", "cshrc"]] + bins + libs,
            'dirs': dirs,
        }

        # run motorBike tutorial case to ensure the installation is functional (if it's available);
        # only for recent (>= v6.0) versions of openfoam.org variant
        if self.looseversion >= LooseVersion('6') and self.looseversion < LooseVersion('100'):
            openfoamdir_path = os.path.join(self.installdir, self.openfoamdir)
            motorbike_path = os.path.join(openfoamdir_path, 'tutorials', 'incompressible', 'simpleFoam', 'motorBike')
            if os.path.exists(motorbike_path):
                cmds = [
                    "cp -a %s %s" % (motorbike_path, self.builddir),
                    "cd %s" % os.path.join(self.builddir, os.path.basename(motorbike_path)),
                    "source $FOAM_BASH",
                    ". $WM_PROJECT_DIR/bin/tools/RunFunctions",
                    "cp $FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz constant/triSurface/",
                    "runApplication surfaceFeatures",
                    "runApplication blockMesh",
                    "runApplication decomposePar -copyZero",
                    "runParallel snappyHexMesh -overwrite",
                    "runParallel patchSummary",
                    "runParallel potentialFoam",
                    "runParallel simpleFoam",
                    "runApplication reconstructParMesh -constant",
                    "runApplication reconstructPar -latestTime",
                    "cd %s" % self.builddir,
                    "rm -r %s" % os.path.basename(motorbike_path),
                ]
                # all commands need to be run in a single shell command,
                # because sourcing $FOAM_BASH sets up environment
                custom_commands.append(' && '.join(cmds))

        super(EB_OpenFOAM, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra(self, altroot=None, altversion=None):
        """Define extra environment variables required by OpenFOAM"""

        txt = super(EB_OpenFOAM, self).make_module_extra()

        env_vars = [
            # Set WM_COMPILE_OPTION in the module file
            # $FOAM_BASH will then pick it up correctly.
            ('WM_COMPILE_OPTION', self.build_type),
            ('WM_PROJECT_VERSION', self.version),
            ('FOAM_INST_DIR', self.installdir),
            ('WM_COMPILER', self.wm_compiler),
            ('WM_MPLIB', self.wm_mplib),
            ('FOAM_BASH', os.path.join(self.installdir, self.openfoamdir, 'etc', 'bashrc')),
            ('FOAM_CSH', os.path.join(self.installdir, self.openfoamdir, 'etc', 'cshrc')),
        ]

        # OpenFOAM >= 3.0.0 can use 64 bit integers
        if 'extend' not in self.name.lower() and self.looseversion >= LooseVersion('3.0'):
            if self.toolchain.options['i8']:
                env_vars += [('WM_LABEL_SIZE', '64')]
            else:
                env_vars += [('WM_LABEL_SIZE', '32')]

        for (env_var, val) in env_vars:
            # check whether value is defined for compatibility with --module-only
            if val:
                txt += self.module_generator.set_environment(env_var, val)

        return txt
