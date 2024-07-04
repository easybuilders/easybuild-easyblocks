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
EasyBuild support for building and installing WPS, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
@author: Andreas Hilboll (University of Bremen)
"""
import os
import re
import tempfile
from easybuild.tools import LooseVersion

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.netcdf import set_netcdf_env_vars
from easybuild.easyblocks.wrf import det_wrf_subdir
from easybuild.framework.easyblock import EasyBlock
from easybuild.framework.easyconfig import CUSTOM, MANDATORY
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import build_option
from easybuild.tools.filetools import apply_regex_substitutions, change_dir, copy_file, extract_file, mkdir
from easybuild.tools.filetools import patch_perl_script_autoflush, remove_dir, symlink
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd, run_cmd_qa


class EB_WPS(EasyBlock):
    """Support for building/installing WPS."""

    def __init__(self, *args, **kwargs):
        """Add extra config options specific to WPS."""

        super(EB_WPS, self).__init__(*args, **kwargs)

        self.build_in_installdir = True
        self.comp_fam = None
        self.compile_script = None
        testdata_urls = ["https://www2.mmm.ucar.edu/wrf/src/data/avn_data.tar.gz"]
        if LooseVersion(self.version) < LooseVersion('3.8'):
            # 697MB download, 16GB unpacked!
            testdata_urls.append("https://www2.mmm.ucar.edu/wrf/src/wps_files/geog.tar.gz")
        elif LooseVersion(self.version) < LooseVersion('4.0'):
            # 2.3GB download!
            testdata_urls.append("https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_complete.tar.gz")
        else:
            # 2.6GB download, 29GB unpacked!!
            testdata_urls.append("https://www2.mmm.ucar.edu/wrf/src/wps_files/geog_high_res_mandatory.tar.gz")
        if self.cfg.get('testdata') is None:
            self.cfg['testdata'] = testdata_urls

        if LooseVersion(self.version) < LooseVersion('4.0'):
            self.wps_subdir = 'WPS'
        else:
            self.wps_subdir = 'WPS-%s' % self.version

    @staticmethod
    def extra_options():
        extra_vars = {
            'buildtype': [None, "Specify the type of build (smpar: OpenMP, dmpar: MPI).", MANDATORY],
            'runtest': [True, "Build and run WPS tests", CUSTOM],
            'testdata': [None, "URL to test data required to run WPS test", CUSTOM],
        }
        return EasyBlock.extra_options(extra_vars)

    def configure_step(self):
        """Configure build:
        - set required environment variables (for netCDF, JasPer)
        - patch compile script and ungrib Makefile for non-default install paths of WRF and JasPer
        - run configure script and figure how to select desired build option
        - patch configure.wps file afterwards to fix 'serial compiler' setting
        """

        # netCDF dependency check + setting env vars (NETCDF, NETCDFF)
        set_netcdf_env_vars(self.log)

        # WRF dependency check
        wrf = get_software_root('WRF')
        if wrf:
            wrfdir = os.path.join(wrf, det_wrf_subdir(get_software_version('WRF')))
        else:
            raise EasyBuildError("WRF module not loaded?")

        self.compile_script = 'compile'

        if LooseVersion(self.version) >= LooseVersion('4.0.3'):
            # specify install location of WRF via $WRF_DIR (supported since WPS 4.0.3)
            # see https://github.com/wrf-model/WPS/pull/102
            env.setvar('WRF_DIR', wrfdir)
        else:
            # patch compile script so that WRF is found
            regex_subs = [(r"^(\s*set\s*WRF_DIR_PRE\s*=\s*)\${DEV_TOP}(.*)$", r"\1%s\2" % wrfdir)]
            apply_regex_substitutions(self.compile_script, regex_subs)

        # libpng dependency check
        libpng = get_software_root('libpng')
        zlib = get_software_root('zlib')
        if libpng:
            paths = [libpng]
            if zlib:
                paths.insert(0, zlib)
            libpnginc = ' '.join(['-I%s' % os.path.join(path, 'include') for path in paths])
            libpnglib = ' '.join(['-L%s' % os.path.join(path, 'lib') for path in paths])
        else:
            # define these as empty, assume that libpng will be available via OS (e.g. due to --filter-deps=libpng)
            libpnglib = ""
            libpnginc = ""

        # JasPer dependency check + setting env vars
        jasper = get_software_root('JasPer')
        if jasper:
            env.setvar('JASPERINC', os.path.join(jasper, "include"))
            jasperlibdir = os.path.join(jasper, "lib")
            env.setvar('JASPERLIB', jasperlibdir)
            jasperlib = "-L%s" % jasperlibdir
        else:
            raise EasyBuildError("JasPer module not loaded?")

        # patch ungrib Makefile so that JasPer is found
        jasperlibs = "%s -ljasper %s -lpng" % (jasperlib, libpnglib)
        regex_subs = [
            (r"^(\s*-L\.\s*-l\$\(LIBTARGET\))(\s*;.*)$", r"\1 %s\2" % jasperlibs),
            (r"^(\s*\$\(COMPRESSION_LIBS\))(\s*;.*)$", r"\1 %s\2" % jasperlibs),
        ]
        apply_regex_substitutions(os.path.join('ungrib', 'src', 'Makefile'), regex_subs)

        # patch arch/Config.pl script, so that run_cmd_qa receives all output to answer questions
        patch_perl_script_autoflush(os.path.join("arch", "Config.pl"))

        # configure

        # determine build type option to look for
        self.comp_fam = self.toolchain.comp_family()
        build_type_option = None

        if LooseVersion(self.version) >= LooseVersion("3.4"):

            knownbuildtypes = {
                'smpar': 'serial',
                'dmpar': 'dmpar'
            }

            if self.comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
                build_type_option = " Linux x86_64, Intel compiler"

            elif self.comp_fam == toolchain.GCC:  # @UndefinedVariable
                if LooseVersion(self.version) >= LooseVersion("3.6"):
                    build_type_option = "Linux x86_64, gfortran"
                else:
                    build_type_option = "Linux x86_64 g95"

            else:
                raise EasyBuildError("Don't know how to figure out build type to select.")

        else:

            knownbuildtypes = {
                'smpar': 'serial',
                'dmpar': 'DM parallel'
            }

            if self.comp_fam == toolchain.INTELCOMP:  # @UndefinedVariable
                build_type_option = "PC Linux x86_64, Intel compiler"

            elif self.comp_fam == toolchain.GCC:  # @UndefinedVariable
                build_type_option = "PC Linux x86_64, gfortran compiler,"
                knownbuildtypes['dmpar'] = knownbuildtypes['dmpar'].upper()

            else:
                raise EasyBuildError("Don't know how to figure out build type to select.")

        # check and fetch selected build type
        bt = self.cfg['buildtype']

        if bt not in knownbuildtypes.keys():
            raise EasyBuildError("Unknown build type: '%s'. Supported build types: %s", bt, knownbuildtypes.keys())

        # fetch option number based on build type option and selected build type
        build_type_question = r"\s*(?P<nr>[0-9]+).\s*%s\s*\(?%s\)?\s*\n" % (build_type_option, knownbuildtypes[bt])

        cmd = ' '.join([
            self.cfg['preconfigopts'],
            './configure',
            self.cfg['configopts'],
        ])
        qa = {}
        no_qa = [".*compiler is.*"]
        std_qa = {
            # named group in match will be used to construct answer
            r"%s(.*\n)*Enter selection\s*\[[0-9]+-[0-9]+\]\s*:" % build_type_question: "%(nr)s",
        }

        run_cmd_qa(cmd, qa, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True)

        # make sure correct compilers and compiler flags are being used
        comps = {
            'SCC': "%s -I$(JASPERINC) %s" % (os.getenv('CC'), libpnginc),
            'SFC': os.getenv('F90'),
            'DM_FC': os.getenv('MPIF90'),
            'DM_CC': os.getenv('MPICC'),
            'FC': os.getenv('MPIF90'),
            'CC': os.getenv('MPICC'),
        }
        if self.toolchain.options.get('openmp', None):
            comps.update({'LDFLAGS': '%s %s' % (self.toolchain.get_flag('openmp'), os.environ['LDFLAGS'])})

        regex_subs = [(r"^(%s\s*=\s*).*$" % key, r"\1 %s" % val) for (key, val) in comps.items()]
        apply_regex_substitutions('configure.wps', regex_subs)

    def build_step(self):
        """Build in install dir using compile script."""
        cmd = ' '.join([
            self.cfg['prebuildopts'],
            './' + self.compile_script,
            self.cfg['buildopts'],
        ])
        run_cmd(cmd, log_all=True, simple=True)

    def test_step(self):
        """Run WPS test (requires large dataset to be downloaded). """

        wpsdir = None

        def run_wps_cmd(cmdname, mpi_cmd=True):
            """Run a WPS command, and check for success."""

            cmd = os.path.join(wpsdir, "%s.exe" % cmdname)

            if mpi_cmd:
                if build_option('mpi_tests'):
                    cmd = self.toolchain.mpi_cmd_for(cmd, 1)
                else:
                    self.log.info("Skipping MPI test for %s, since MPI tests are disabled", cmd)
                    return

            (out, _) = run_cmd(cmd, log_all=True, simple=False)

            re_success = re.compile("Successful completion of %s" % cmdname)
            if not re_success.search(out):
                raise EasyBuildError("%s.exe failed (pattern '%s' not found)?", cmdname, re_success.pattern)

        if self.cfg['runtest']:
            if not self.cfg['testdata']:
                raise EasyBuildError("List of URLs for testdata not provided.")

            wpsdir = os.path.join(self.builddir, self.wps_subdir)

            try:
                # create temporary directory
                tmpdir = tempfile.mkdtemp()
                change_dir(tmpdir)

                # download data
                testdata_paths = []
                for testdata in self.cfg['testdata']:
                    path = self.obtain_file(testdata)
                    if not path:
                        raise EasyBuildError("Downloading file from %s failed?", testdata)
                    testdata_paths.append(path)

                # unpack data
                for path in testdata_paths:
                    srcdir = extract_file(path, tmpdir, change_into_dir=False)
                    change_dir(srcdir)

                namelist_file = os.path.join(tmpdir, 'namelist.wps')

                # GEOGRID

                # setup directories and files
                if LooseVersion(self.version) < LooseVersion("4.0"):
                    geog_data_dir = "geog"
                else:
                    geog_data_dir = "WPS_GEOG"
                for dir_name in os.listdir(os.path.join(tmpdir, geog_data_dir)):
                    symlink(os.path.join(tmpdir, geog_data_dir, dir_name), os.path.join(tmpdir, dir_name))

                # copy namelist.wps file and patch it for geogrid
                copy_file(os.path.join(wpsdir, 'namelist.wps'), namelist_file)
                regex_subs = [(r"^(\s*geog_data_path\s*=\s*).*$", r"\1 '%s'" % tmpdir)]
                apply_regex_substitutions(namelist_file, regex_subs)

                # GEOGRID.TBL
                geogrid_dir = os.path.join(tmpdir, 'geogrid')
                mkdir(geogrid_dir)
                symlink(os.path.join(wpsdir, 'geogrid', 'GEOGRID.TBL.ARW'),
                        os.path.join(geogrid_dir, 'GEOGRID.TBL'))

                # run geogrid.exe
                run_wps_cmd("geogrid")

                # UNGRIB

                # determine start and end time stamps of grib files
                grib_file_prefix = "fnl_"
                k = len(grib_file_prefix)
                fs = [f for f in sorted(os.listdir('.')) if f.startswith(grib_file_prefix)]
                start = "%s:00:00" % fs[0][k:]
                end = "%s:00:00" % fs[-1][k:]

                # copy namelist.wps file and patch it for ungrib
                copy_file(os.path.join(wpsdir, 'namelist.wps'), namelist_file)
                regex_subs = [
                    (r"^(\s*start_date\s*=\s*).*$", r"\1 '%s','%s'," % (start, start)),
                    (r"^(\s*end_date\s*=\s*).*$", r"\1 '%s','%s'," % (end, end)),
                ]
                apply_regex_substitutions(namelist_file, regex_subs)

                # copy correct Vtable
                vtable_dir = os.path.join(wpsdir, 'ungrib', 'Variable_Tables')
                if os.path.exists(os.path.join(vtable_dir, 'Vtable.ARW')):
                    copy_file(os.path.join(vtable_dir, 'Vtable.ARW'), os.path.join(tmpdir, 'Vtable'))
                elif os.path.exists(os.path.join(vtable_dir, 'Vtable.ARW.UPP')):
                    copy_file(os.path.join(vtable_dir, 'Vtable.ARW.UPP'), os.path.join(tmpdir, 'Vtable'))
                else:
                    raise EasyBuildError("Could not find Vtable file to use for testing ungrib")

                # run link_grib.csh script
                cmd = "%s %s*" % (os.path.join(wpsdir, "link_grib.csh"), grib_file_prefix)
                run_cmd(cmd, log_all=True, simple=True)

                # run ungrib.exe
                run_wps_cmd("ungrib", mpi_cmd=False)

                # METGRID.TBL

                metgrid_dir = os.path.join(tmpdir, 'metgrid')
                mkdir(metgrid_dir)
                symlink(os.path.join(wpsdir, 'metgrid', 'METGRID.TBL.ARW'),
                        os.path.join(metgrid_dir, 'METGRID.TBL'))

                # run metgrid.exe
                run_wps_cmd('metgrid')

                # clean up
                change_dir(self.builddir)
                remove_dir(tmpdir)

            except OSError as err:
                raise EasyBuildError("Failed to run WPS test: %s", err)

    # installing is done in build_step, so we can run tests
    def install_step(self):
        """Building was done in install dir, so just do some cleanup here."""

        # make sure JASPER environment variables are unset
        env_vars = ['JASPERINC', 'JASPERLIB']

        for env_var in env_vars:
            if env_var in os.environ:
                os.environ.pop(env_var)

    def sanity_check_step(self):
        """Custom sanity check for WPS."""

        custom_paths = {
            'files': [os.path.join(self.wps_subdir, x) for x in ['geogrid.exe', 'metgrid.exe', 'ungrib.exe']],
            'dirs': [],
        }
        super(EB_WPS, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Make sure PATH and LD_LIBRARY_PATH are set correctly."""
        return {
            'PATH': [self.wps_subdir, os.path.join(self.wps_subdir, 'util')],
            'LD_LIBRARY_PATH': [self.wps_subdir],
            'MANPATH': [],
        }

    def make_module_extra(self):
        """Add netCDF environment variables to module file."""
        txt = super(EB_WPS, self).make_module_extra()
        for var in ['NETCDF', 'NETCDFF']:
            # check whether value is defined for compatibility with --module-only
            if os.getenv(var) is not None:
                txt += self.module_generator.set_environment(var, os.getenv(var))
        return txt
