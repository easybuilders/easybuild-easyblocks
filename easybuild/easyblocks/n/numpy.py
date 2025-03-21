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
EasyBuild support for building and installing numpy, implemented as an easyblock

@author: Stijn De Weirdt (Ghent University)
@author: Dries Verdegem (Ghent University)
@author: Kenneth Hoste (Ghent University)
@author: Pieter De Baets (Ghent University)
@author: Jens Timmerman (Ghent University)
"""
import glob
import os
import re
import tempfile

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.fortranpythonpackage import FortranPythonPackage
from easybuild.easyblocks.generic.pythonpackage import det_pylibdir
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import change_dir, mkdir, read_file, remove_dir
from easybuild.tools.modules import get_software_root
from easybuild.tools.run import run_shell_cmd
from easybuild.tools import LooseVersion


class EB_numpy(FortranPythonPackage):
    """Support for installing the numpy Python package as part of a Python installation."""

    @staticmethod
    def extra_options():
        """Easyconfig parameters specific to numpy."""
        extra_vars = ({
            'blas_test_time_limit': [500, "Time limit (in ms) for 1000x1000 matrix dot product BLAS test", CUSTOM],
            'ignore_test_result': [False, "Run numpy test suite, but ignore test result (only log)", CUSTOM],
        })
        return FortranPythonPackage.extra_options(extra_vars=extra_vars)

    def __init__(self, *args, **kwargs):
        """Initialize numpy-specific class variables."""
        super(EB_numpy, self).__init__(*args, **kwargs)

        self.sitecfg = None
        self.sitecfgfn = 'site.cfg'
        self.testinstall = True

    def configure_step(self):
        """Configure numpy build by composing site.cfg contents."""

        # see e.g. https://github.com/numpy/numpy/pull/2809/files
        self.sitecfg = '\n'.join([
            "[DEFAULT]",
            "library_dirs = %(libs)s",
            "include_dirs= %(includes)s",
            "search_static_first=True",
        ])

        # If both FlexiBLAS and MKL are found, we assume that FlexiBLAS has a dependency on MKL.
        # In this case we want to link to FlexiBLAS and not directly to MKL.
        imkl_direct = get_software_root("imkl") and not get_software_root("FlexiBLAS")

        if imkl_direct:

            if self.toolchain.comp_family() == toolchain.GCC:
                # see https://software.intel.com/en-us/articles/numpyscipy-with-intel-mkl,
                # section Building with GNU Compiler chain
                extrasiteconfig = '\n'.join([
                    "[mkl]",
                    "lapack_libs = ",
                    "mkl_libs = mkl_rt",
                ])
            else:
                extrasiteconfig = '\n'.join([
                    "[mkl]",
                    "lapack_libs = %(lapack)s",
                    "mkl_libs = %(blas)s",
                ])

        else:
            # [atlas] the only real alternative, even for non-ATLAS BLAS libs (e.g., OpenBLAS, ACML, ...)
            # using only the [blas] and [lapack] sections results in sub-optimal builds that don't provide _dotblas.so;
            # it does require a CBLAS interface to be available for the BLAS library being used
            # e.g. for ACML, the CBLAS module providing a C interface needs to be used
            extrasiteconfig = '\n'.join([
                "[atlas]",
                "atlas_libs = %(lapack)s",
                "[lapack]",
                "lapack_libs = %(lapack)s",  # required by scipy, that uses numpy's site.cfg
            ])

        blas = None
        lapack = None
        fft = None

        if imkl_direct:
            # with IMKL, no spaces and use '-Wl:'
            # redefine 'Wl,' to 'Wl:' so that the patch file can do its job
            def get_libs_for_mkl(varname):
                """Get list of libraries as required for MKL patch file."""
                libs = self.toolchain.variables['LIB%s' % varname].copy()
                libs.try_remove(['pthread', 'dl'])
                tweaks = {
                    'prefix': '',
                    'prefix_begin_end': '-Wl:',
                    'separator': ',',
                    'separator_begin_end': ',',
                }
                libs.try_function_on_element('change', kwargs=tweaks)
                libs.SEPARATOR = ','
                return str(libs)  # str causes list concatenation and adding prefixes & separators

            blas = get_libs_for_mkl('BLAS_MT')
            lapack = get_libs_for_mkl('LAPACK_MT')
            fft = get_libs_for_mkl('FFT')

            # make sure the patch file is there
            # we check for a typical characteristic of a patch file that cooperates with the above
            # not fool-proof, but better than enforcing a particular patch filename
            patch_found = False
            patch_wl_regex = re.compile(r"replace\(':',\s*','\)")
            for patch in self.patches:
                # patches are either strings (extension) or dicts (easyblock)
                if isinstance(patch, dict):
                    patch = patch['path']
                if patch_wl_regex.search(read_file(patch)):
                    patch_found = True
                    break
            if not patch_found:
                raise EasyBuildError("Building numpy on top of Intel MKL requires a patch to "
                                     "handle -Wl linker flags correctly, which doesn't seem to be there.")

        else:
            # unless Intel MKL is used, $ATLAS should be set to take full control,
            # and to make sure a fully optimized version is built, including _dotblas.so
            # which is critical for decent performance of the numpy.dot (matrix dot product) function!
            env.setvar('ATLAS', '1')

            lapack = ', '.join([x for x in self.toolchain.get_variable('LIBLAPACK_MT', typ=list) if x != "pthread"])
            fft = ', '.join(self.toolchain.get_variable('LIBFFT', typ=list))

        libs = ':'.join(self.toolchain.get_variable('LDFLAGS', typ=list))
        includes = ':'.join(self.toolchain.get_variable('CPPFLAGS', typ=list))

        # CBLAS is required for ACML, because it doesn't offer a C interface to BLAS
        if get_software_root('ACML'):
            cblasroot = get_software_root('CBLAS')
            if cblasroot:
                lapack = ', '.join([lapack, "cblas"])
                cblaslib = os.path.join(cblasroot, 'lib')
                # with numpy as extension, CBLAS might not be included in LDFLAGS because it's not part of a toolchain
                if cblaslib not in libs:
                    libs = ':'.join([libs, cblaslib])
            else:
                raise EasyBuildError("CBLAS is required next to ACML to provide a C interface to BLAS, "
                                     "but it's not loaded.")

        if fft:
            extrasiteconfig += "\n[fftw]\nlibraries = %s" % fft

        suitesparseroot = get_software_root('SuiteSparse')
        if suitesparseroot:

            extrasiteconfig += '\n'.join([
                "[amd]",
                "library_dirs = %s" % os.path.join(suitesparseroot, 'lib'),
                "include_dirs = %s" % os.path.join(suitesparseroot, 'include'),
                "amd_libs = amd",
                "[umfpack]",
                "library_dirs = %s" % os.path.join(suitesparseroot, 'lib'),
                "include_dirs = %s" % os.path.join(suitesparseroot, 'include'),
                "umfpack_libs = umfpack",
            ])

        self.sitecfg = '\n'.join([self.sitecfg, extrasiteconfig])

        self.sitecfg = self.sitecfg % {
            'blas': blas,
            'lapack': lapack,
            'libs': libs,
            'includes': includes,
        }

        if LooseVersion(self.version) < LooseVersion('1.26'):
            # NumPy detects the required math by trying to link a minimal code containing a call to `log(0.)`.
            # The first try is without any libraries, which works with `gcc -fno-math-errno` (our optimization default)
            # because the call gets removed due to not having any effect. So it concludes that `-lm` is not required.
            # This then fails to detect availability of functions such as `acosh` which do not get removed in the same
            # way and so less exact replacements are used instead which e.g. fail the tests on PPC.
            # This variable makes it try `-lm` first and is supported until the Meson backend is used in 1.26+.
            env.setvar('MATHLIB', 'm')

        super(EB_numpy, self).configure_step()

        if LooseVersion(self.version) < LooseVersion('1.21'):
            # check configuration (for debugging purposes)
            cmd = "%s setup.py config" % self.python_cmd
            run_shell_cmd(cmd)

        if LooseVersion(self.version) >= LooseVersion('1.26'):
            # control BLAS/LAPACK library being used
            # see https://github.com/numpy/numpy/blob/v1.26.2/doc/source/release/1.26.1-notes.rst#build-system-changes
            # and 'blas-order' in https://github.com/numpy/numpy/blob/v1.26.2/meson_options.txt
            blas_lapack_names = {
                toolchain.BLIS: 'blis',
                toolchain.FLEXIBLAS: 'flexiblas',
                toolchain.LAPACK: 'lapack',
                toolchain.INTELMKL: 'mkl',
                toolchain.OPENBLAS: 'openblas',
            }
            blas_family = self.toolchain.blas_family()
            if blas_family in blas_lapack_names:
                self.cfg.update('installopts', "-Csetup-args=-Dblas=" + blas_lapack_names[blas_family])
            else:
                raise EasyBuildError("Unknown BLAS library for numpy %s: %s", self.version, blas_family)

            lapack_family = self.toolchain.lapack_family()
            if lapack_family in blas_lapack_names:
                self.cfg.update('installopts', "-Csetup-args=-Dlapack=" + blas_lapack_names[lapack_family])
            else:
                raise EasyBuildError("Unknown LAPACK library for numpy %s: %s", self.version, lapack_family)

            self.cfg.update('installopts', "-Csetup-args=-Dallow-noblas=false")

    def test_step(self):
        """Run available numpy unit tests, and more."""

        # determine command to use to run numpy test suite,
        # and whether test results should be ignored or not
        if self.cfg['ignore_test_result']:
            test_code = 'numpy.test(verbose=2)'
        else:
            if LooseVersion(self.version) >= LooseVersion('1.15'):
                # Numpy 1.15+ returns a True on success. Hence invert to get a failure value
                test_code = 'sys.exit(not numpy.test(verbose=2))'
            else:
                # Return value is a TextTestResult. Check the errors member for any error
                test_code = 'sys.exit(len(numpy.test(verbose=2).errors) > 0)'

        # Prepend imports
        test_code = "import sys; import numpy; " + test_code

        # LDFLAGS should not be set when testing numpy/scipy, because it overwrites whatever numpy/scipy sets
        # see http://projects.scipy.org/numpy/ticket/182
        self.testcmd = "unset LDFLAGS && cd .. && %%(python)s -c '%s'" % test_code

        super(EB_numpy, self).test_step()

        # temporarily install numpy, it doesn't alow to be used straight from the source dir
        tmpdir = tempfile.mkdtemp()
        abs_pylibdirs = [os.path.join(tmpdir, pylibdir) for pylibdir in self.all_pylibdirs]
        for pylibdir in abs_pylibdirs:
            mkdir(pylibdir, parents=True)
        pythonpath = "export PYTHONPATH=%s &&" % os.pathsep.join(abs_pylibdirs + ['$PYTHONPATH'])
        cmd = self.compose_install_command(tmpdir, extrapath=pythonpath)
        run_shell_cmd(cmd)

        try:
            pwd = os.getcwd()
            os.chdir(tmpdir)
        except OSError as err:
            raise EasyBuildError("Faild to change to %s: %s", tmpdir, err)

        # evaluate performance of numpy.dot (3 runs, 3 loops each)
        size = 1000
        cmd = ' '.join([
            pythonpath,
            '%s -m timeit -n 3 -r 3' % self.python_cmd,
            '-s "import numpy; x = numpy.random.random((%(size)d, %(size)d))"' % {'size': size},
            '"numpy.dot(x, x.T)"',
        ])
        res = run_shell_cmd(cmd)
        self.log.debug("Test output: %s" % res.output)

        # fetch result
        time_msec = None
        msec_re = re.compile(r"\d+ loops, best of \d+: (?P<time>[0-9.]+) msec per loop")
        msec = msec_re.search(res.output)
        if msec:
            time_msec = float(msec.group('time'))
        else:
            sec_re = re.compile(r"\d+ loops, best of \d+: (?P<time>[0-9.]+) sec per loop")
            sec = sec_re.search(res.output)
            if sec:
                time_msec = 1000 * float(sec.group('time'))
            elif self.dry_run:
                # use fake value during dry run
                time_msec = 123
                self.log.warning("Using fake value for time required for %dx%d matrix dot product under dry run: %s",
                                 size, size, time_msec)
            else:
                raise EasyBuildError("Failed to determine time for numpy.dot test run.")

        # make sure we observe decent performance
        if time_msec < self.cfg['blas_test_time_limit']:
            self.log.info("Time for %dx%d matrix dot product: %d msec < %d msec => OK",
                          size, size, time_msec, self.cfg['blas_test_time_limit'])
        else:
            raise EasyBuildError("Time for %dx%d matrix dot product: %d msec >= %d msec => ERROR",
                                 size, size, time_msec, self.cfg['blas_test_time_limit'])
        try:
            os.chdir(pwd)
            remove_dir(tmpdir)
        except OSError as err:
            raise EasyBuildError("Failed to change back to %s: %s", pwd, err)

    def install_step(self):
        """Install numpy and remove numpy build dir, so scipy doesn't find it by accident."""
        super(EB_numpy, self).install_step()

        builddir = os.path.join(self.builddir, "numpy")
        try:
            if os.path.isdir(builddir):
                os.chdir(self.builddir)
                remove_dir(builddir)
            else:
                self.log.debug("build dir %s already clean" % builddir)

        except OSError as err:
            raise EasyBuildError("Failed to clean up numpy build dir %s: %s", builddir, err)

    def install_extension(self):
        """Install numpy as an extension"""
        super(EB_numpy, self).install_extension()

        return self.make_module_extra_numpy_include()

    def sanity_check_step(self, *args, **kwargs):
        """Custom sanity check for numpy."""

        # can't use self.pylibdir here, need to determine path on the fly using currently active 'python' command;
        # this is important for numpy installations for multiple Python version (via multi_deps)
        custom_paths = {
            'files': [],
            'dirs': [det_pylibdir()],
        }

        custom_commands = []

        if LooseVersion(self.version) >= LooseVersion('1.26'):
            # make sure BLAS library was found
            blas_check_pytxt = '; '.join([
                "import numpy",
                "numpy_config = numpy.show_config(mode='dicts')",
                "numpy_build_deps = numpy_config['Build Dependencies']",
                "blas_found = numpy_build_deps['blas']['found']",
                "assert blas_found",
            ])
            custom_commands.append('python -s -c "%s"' % blas_check_pytxt)

            # if FlexiBLAS is used, make sure we are linking to it
            # (rather than directly to a backend library like OpenBLAS or Intel MKL)
            if self.toolchain.blas_family() == toolchain.FLEXIBLAS:
                blas_check_pytxt = '; '.join([
                    "import numpy",
                    "numpy_config = numpy.show_config(mode='dicts')",
                    "numpy_build_deps = numpy_config['Build Dependencies']",
                    "blas_name = numpy_build_deps['blas']['name']",
                    "assert blas_name == 'flexiblas', 'BLAS library should be flexiblas, found %s' % blas_name",
                ])
                custom_commands.append('python -s -c "%s"' % blas_check_pytxt)

        elif LooseVersion(self.version) >= LooseVersion('1.10'):
            # generic check to see whether numpy v1.10.x and up was built against a CBLAS-enabled library
            # cfr. https://github.com/numpy/numpy/issues/6675#issuecomment-162601149
            blas_check_pytxt = '; '.join([
                "import sys",
                "import numpy",
                "blas_ok = 'HAVE_CBLAS' in dict(numpy.__config__.blas_opt_info['define_macros'])",
                "sys.exit((1, 0)[blas_ok])",
            ])
            custom_commands.append('python -s -c "%s"' % blas_check_pytxt)
        else:
            # _dotblas is required for decent performance of numpy.dot(), but only there in numpy 1.9.x and older
            custom_commands.append("python -s -c 'import numpy.core._dotblas'")

        return super(EB_numpy, self).sanity_check_step(custom_paths=custom_paths, custom_commands=custom_commands)

    def make_module_extra_numpy_include(self):
        """
        Return update statements for $CPATH specifically for numpy
        """
        numpy_core_subdir = os.path.join('numpy', 'core')
        numpy_core_dirs = []
        cwd = change_dir(self.installdir)
        for pylibdir in self.all_pylibdirs:
            numpy_core_dirs.extend(glob.glob(os.path.join(pylibdir, numpy_core_subdir)))
            numpy_core_dirs.extend(glob.glob(os.path.join(pylibdir, 'numpy*.egg', numpy_core_subdir)))
        change_dir(cwd)

        txt = ''
        for numpy_core_dir in numpy_core_dirs:
            txt += self.module_generator.prepend_paths('CPATH', os.path.join(numpy_core_dir, 'include'))
            for lib_env_var in ('LD_LIBRARY_PATH', 'LIBRARY_PATH'):
                txt += self.module_generator.prepend_paths(lib_env_var, os.path.join(numpy_core_dir, 'lib'))

        return txt

    def make_module_extra(self):
        """
        Add additional update statements in module file specific to numpy
        """
        txt = super(EB_numpy, self).make_module_extra()
        txt += self.make_module_extra_numpy_include()
        return txt
