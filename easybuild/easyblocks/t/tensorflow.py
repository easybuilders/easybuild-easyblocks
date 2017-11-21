##
# Copyright 2009-2017 Ghent University
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
EasyBuild support for building and installing TensorFlow, implemented as an easyblock
"""
import glob
import os
import stat
import tempfile

import easybuild.tools.environment as env
import easybuild.tools.toolchain as toolchain
from easybuild.easyblocks.generic.pythonpackage import PythonPackage
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, apply_regex_substitutions, mkdir, resolve_path
from easybuild.tools.filetools import which, write_file
from easybuild.tools.modules import get_software_root, get_software_version
from easybuild.tools.run import run_cmd, run_cmd_qa


INTEL_COMPILER_WRAPPER = """#!/bin/bash
export INTEL_LICENSE_FILE='%(intel_license_file)s'
%(compiler_path)s "$@"
"""


class EB_TensorFlow(PythonPackage):
    """Support for building/installing TensorFlow."""

    @staticmethod
    def extra_options():
        extra_vars = {
            # see https://developer.nvidia.com/cuda-gpus
            'cuda_compute_capabilities': [[], "List of CUDA compute capabilities to build with", CUSTOM],
        }
        return PythonPackage.extra_options(extra_vars)

    def configure_step(self):
        """Custom configuration procedure for TensorFlow."""

        tmpdir = tempfile.mkdtemp(suffix='-bazel-configure')

        self.prepare_python()

        cuda_root = get_software_root('CUDA')
        jemalloc_root = get_software_root('jemalloc')
        mkl_root = get_software_root('imkl')
        opencl_root = get_software_root('OpenCL')

        use_mpi = self.toolchain.options.get('usempi', False)

        qa = {
            "Do you wish to build TensorFlow with Amazon S3 File System support? [Y/n]:": 'n',
            "Do you wish to build TensorFlow with CUDA support? [y/N]:": ('n', 'y')[bool(cuda_root)],
            "Do you wish to build TensorFlow with GDR support? [y/N]:": 'n',
            "Do you wish to build TensorFlow with Google Cloud Platform support? [Y/n]:": 'n',
            "Do you wish to build TensorFlow with Hadoop File System support? [Y/n]:": 'n',
            "Do you wish to build TensorFlow with jemalloc as malloc support? [Y/n]:": ('n', 'y')[bool(jemalloc_root)],
            "Do you wish to build TensorFlow with OpenCL support? [y/N]:": ('n', 'y')[bool(opencl_root)],
            "Do you wish to build TensorFlow with MKL support? [y/N]": ('n', 'y')[bool(mkl_root)],
            "Do you wish to build TensorFlow with MPI support? [y/N]:": ('n', 'y')[use_mpi],
            "Do you wish to build TensorFlow with XLA JIT support? [y/N]:": 'n',
            "Do you wish to build TensorFlow with VERBS support? [y/N]:": 'n',
        }
        no_qa = ["Extracting Bazel installation..."]
        std_qa = {
            "Please specify the location of python.*": self.python_cmd,
            "Please input the desired Python library path to use.*": os.path.join(self.installdir, self.pylibdir),
            "Please specify optimization flags to use during compilation.*": os.getenv('CXXFLAGS'),
            "Please specify the MPI toolkit folder.*": '',
        }
        if cuda_root:
            cuda_ver = get_software_version('CUDA')
            cuda_majver = '.'.join(cuda_ver.split('.')[:2])
            cuda_comp_caps = ','.join(self.cfg['cuda_compute_capabilities'])
            qa.update({
                "Do you want to use clang as CUDA compiler? [y/N]:": 'n',
            })
            std_qa.update({
                "Please specify the CUDA SDK version you want to use.*": cuda_ver,
                "Please specify the location where CUDA .* toolkit is installed.*": cuda_root,
                "Please specify which gcc should be used by nvcc as the host compiler.*": which('gcc'),
                "Please specify a list of comma-separated Cuda compute capabilities.*\n.*\n.*": cuda_comp_caps,
            })

        cudnn_root = get_software_root('cuDNN')
        if cudnn_root:
            std_qa.update({
                "Please specify the location where cuDNN .* library is installed.*": cudnn_root,
                "Please specify the cuDNN version you want to use.*": get_software_version('cuDNN'),
            })

        # patch configure.py (called by configure script) to avoid that Bazel abuses $HOME/.cache/bazel
        regex_subs = [(r"(run_shell\(\['bazel')", r"\1, '--output_base=%s'" % tmpdir)]
        apply_regex_substitutions('configure.py', regex_subs)

        # create wrapper for icc to make sure location of license server is available...
        # cfr. https://github.com/bazelbuild/bazel/issues/663
        if self.toolchain.comp_family() == toolchain.INTELCOMP:
            icc_wrapper_txt = INTEL_COMPILER_WRAPPER % {
                'compiler_path': which('icc'),
                'intel_license_file': os.getenv('INTEL_LICENSE_FILE', os.getenv('LM_LICENSE_FILE')),
            }
            icc_wrapper = os.path.join(tmpdir, 'bin', 'icc')
            write_file(icc_wrapper, icc_wrapper_txt)
            adjust_permissions(icc_wrapper, stat.S_IXUSR)
            env.setvar('PATH', ':'.join([os.path.dirname(icc_wrapper), os.getenv('PATH')]))
            self.log.info("Using wrapper script for 'icc': %s", which('icc'))

        run_cmd_qa('./configure', qa, no_qa=no_qa, std_qa=std_qa, log_all=True, simple=True)

    def build_step(self):
        """Custom build procedure for TensorFlow."""

        # pre-create target installation directory
        mkdir(os.path.join(self.installdir, self.pylibdir), parents=True)

        # patch all CROSSTOOL* scripts to fix hardcoding of locations of binutils/GCC binaries
        binutils_root = get_software_root('binutils')
        if not binutils_root:
            raise EasyBuildError("Failed to determine installation prefix for binutils")

        gcc_root = get_software_root('GCCcore') or get_software_root('GCC')
        if gcc_root:
            gcc_ver = get_software_version('GCCcore') or get_software_version('GCC')
            res = glob.glob(os.path.join(gcc_root, 'lib', 'gcc', '*', gcc_ver, 'include'))
            if res and len(res) == 1:
                gcc_lib_inc = res[0]
            else:
                raise EasyBuildError("Failed to pinpoint location of GCC include files: %s", res)

            gcc_lib_inc_fixed = os.path.join(os.path.dirname(gcc_lib_inc), 'include-fixed')
            if not os.path.exists(gcc_lib_inc_fixed):
                raise EasyBuildError("Derived directory %s does not exist", gcc_lib_inc_fixed)

            gcc_cplusplus_inc = os.path.join(gcc_root, 'include', 'c++', gcc_ver)
            if not os.path.exists(gcc_cplusplus_inc):
                raise EasyBuildError("Derived directory %s does not exist", gcc_cplusplus_inc)
        else:
            raise EasyBuildError("Failed to determine installation prefix for GCC")

        gcc_inc_paths = [gcc_lib_inc, gcc_lib_inc_fixed, gcc_cplusplus_inc]
        regex_subs = [
            #(r'-B/usr/bin', '-B%s -L%s' %( os.path.join(binutils_root, 'bin')),
            (r'-B/usr/bin/', '-B%s/ -L%s/' % (os.path.join(binutils_root, 'bin'), os.path.join(gcc_root, 'lib64'))),
            (r'(cxx_builtin_include_directory:).*', '\n'.join(r'\1 "%s"' % resolve_path(p) for p in gcc_inc_paths)),
        ]
        for tool in ['ar', 'cpp', 'dwp', 'gcc', 'gcov', 'ld', 'nm', 'objcopy', 'objdump', 'strip']:
            path = which(tool)
            if path:
                regex_subs.append((os.path.join('/usr', 'bin', tool), path))
            else:
                raise EasyBuildError("Failed to determine path to '%s'", tool)

        for path, dirnames, filenames in os.walk(self.cfg['start_dir']):
            for filename in filenames:
                if filename.startswith('CROSSTOOL'):
                    apply_regex_substitutions(os.path.join(path, filename), regex_subs)

        tmpdir = tempfile.mkdtemp(suffix='-bazel-build')
        cmd = ['bazel', '--output_base=%s' % tmpdir, 'build', '-s', '--config=opt', '--verbose_failures']
        cmd.append(self.cfg['buildopts'])

        # pass through environment variables that may specify location of license file for Intel compilers
        for key in []:
            if os.getenv(key):
                cmd.append('--action_env=%s' % key)

        if get_software_root('CUDA'):
            cmd.append('--config=cuda')

        imkl_root = get_software_root('imkl')
        if imkl_root:
            cmd.extend(['--config=mkl'])

        cmd.append('//tensorflow/tools/pip_package:build_pip_package')

        run_cmd(' '.join(cmd), log_all=True, simple=True, log_ok=True)

        cmd = "bazel-bin/tensorflow/tools/pip_package/build_pip_package %s" % self.builddir
        run_cmd(cmd, log_all=True, simple=True, log_ok=True)

    def test_step(self):
        """Custom built-in test procedure for TensorFlow."""
        if self.cfg['runtest']:
            tmpdir = tempfile.mkdtemp(suffix='-bazel-test')
            for subsuite in ['core', 'python']:
                run_cmd("bazel --output_base=%s test --config=opt //tensorflow/%s/..." % (tmpdir, subsuite))

    def install_step(self):
        """Custom install procedure for TensorFlow."""
        whl_paths = glob.glob(os.path.join(self.builddir, 'tensorflow-%s-*.whl' % self.version))
        if len(whl_paths) == 1:
            # --upgrade is required to ensure *this* wheel is installed
            # cfr. https://github.com/tensorflow/tensorflow/issues/7449
            cmd = "pip install --ignore-installed --prefix=%s %s" % (self.installdir, whl_paths[0])
            run_cmd(cmd, log_all=True, simple=True, log_ok=True)
        else:
            raise EasyBuildError("Failed to isolate built .whl in %s: %s", whl_paths, self.builddir)

    def sanity_check_step(self):
        """Custom sanity check for TensorFlow."""
        custom_paths = {
            'files': ['bin/tensorboard'],
            'dirs': [self.pylibdir],
        }
        custom_commands = [
            "python -c 'import tensorflow'",
            # tf_should_use importsweakref.finalize, which requires backports.weakref for Python < 3.4
            "python -c 'from tensorflow.python.util import tf_should_use'",
        ]
        super(EB_TensorFlow, self).sanity_check_step(custom_paths=custom_paths)
