##
# Copyright 2012-2025 Ghent University
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
EasyBuild support for CUDA, implemented as an easyblock

Ref: https://speakerdeck.com/ajdecon/introduction-to-the-cuda-toolkit-for-building-applications

@author: George Tsouloupas (Cyprus Institute)
@author: Fotis Georgatos (Uni.lu)
@author: Kenneth Hoste (Ghent University)
@author: Damian Alvarez (Forschungszentrum Juelich)
@author: Ward Poelmans (Free University of Brussels)
@author: Robert Mijakovic (LuxProvide S.A.)
"""
import os
import re
import stat

from easybuild.tools import LooseVersion

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import IGNORE
from easybuild.tools.filetools import adjust_permissions, change_dir, copy_dir, expand_glob_paths
from easybuild.tools.filetools import patch_perl_script_autoflush, remove_file, symlink, which, write_file
from easybuild.tools.run import run_shell_cmd
from easybuild.tools.systemtools import AARCH64, POWER, X86_64, get_cpu_architecture, get_shared_lib_ext
import easybuild.tools.environment as env

# Wrapper script definition
WRAPPER_TEMPLATE = """#!/bin/sh
echo "$@" | grep -e '-ccbin' -e '--compiler-bindir' > /dev/null
if [ $? -eq 0 ];
then
        echo "ERROR: do not set -ccbin or --compiler-bindir when using the `basename $0` wrapper"
else
        nvcc -ccbin=%s "$@"
        exit $?
fi """


class EB_CUDA(Binary):
    """
    Support for installing CUDA.
    """

    @staticmethod
    def extra_options():
        """Create a set of wrappers based on a list determined by the easyconfig file"""
        extra_vars = {
            'host_compilers': [None, "Host compilers for which a wrapper will be generated", CUSTOM]
        }
        return Binary.extra_options(extra_vars)

    def __init__(self, *args, **kwargs):
        """ Init the cuda easyblock adding a new cudaarch template var """
        myarch = get_cpu_architecture()
        if myarch == AARCH64:
            cudaarch = '_sbsa'
        elif myarch == POWER:
            cudaarch = '_ppc64le'
        elif myarch == X86_64:
            cudaarch = ''
        else:
            raise EasyBuildError("Architecture %s is not supported for CUDA on EasyBuild", myarch)

        super(EB_CUDA, self).__init__(*args, **kwargs)

        self.cfg.template_values['cudaarch'] = cudaarch
        self.cfg.generate_template_values()

        # Specify CUDA custom values for module load environment
        # The dirs should be in the order ['open64/bin', 'bin']
        bin_path = []
        if LooseVersion(self.version) < LooseVersion('7'):
            bin_path.append(os.path.join('open64', 'bin'))
        bin_path.append('bin')

        lib_path = ['lib64']
        inc_path = ['include']
        if LooseVersion(self.version) >= LooseVersion('7'):
            lib_path.append(os.path.join('extras', 'CUPTI', 'lib64'))
            inc_path.append(os.path.join('extras', 'CUPTI', 'include'))
            bin_path.append(os.path.join('nvvm', 'bin'))
            lib_path.append(os.path.join('nvvm', 'lib64'))
            inc_path.append(os.path.join('nvvm', 'include'))

        self.module_load_environment.CPATH = inc_path
        self.module_load_environment.LD_LIBRARY_PATH = lib_path
        self.module_load_environment.LIBRARY_PATH = lib_path + [os.path.join('stubs', 'lib64')]
        self.module_load_environment.PATH = bin_path
        self.module_load_environment.PKG_CONFIG_PATH = ['pkgconfig']

    def fetch_step(self, *args, **kwargs):
        """Check for EULA acceptance prior to getting sources."""
        # EULA for CUDA must be accepted via --accept-eula-for EasyBuild configuration option,
        # or via 'accept_eula = True' in easyconfig file
        self.check_accepted_eula(
            name='CUDA',
            more_info='https://docs.nvidia.com/cuda/eula/index.html'
        )
        return super(EB_CUDA, self).fetch_step(*args, **kwargs)

    def extract_step(self):
        """Extract installer to have more control, e.g. options, patching Perl scripts, etc."""
        execpath = self.src[0]['path']
        run_shell_cmd("/bin/sh " + execpath + " --noexec --nox11 --target " + self.builddir)
        self.src[0]['finalpath'] = self.builddir

    def install_step(self):
        """Install CUDA using Perl install script."""

        # define how to run the installer
        # script has /usr/bin/perl hardcoded, but we want to have control over which perl is being used
        if LooseVersion(self.version) <= LooseVersion("5"):
            install_interpreter = "perl"
            install_script = "install-linux.pl"
            self.cfg.update('installopts', '--prefix=%s' % self.installdir)
        elif LooseVersion(self.version) > LooseVersion("5") and LooseVersion(self.version) < LooseVersion("10.1"):
            install_interpreter = "perl"
            install_script = "cuda-installer.pl"
            # note: samples are installed by default
            self.cfg.update('installopts', "-verbose -silent -toolkitpath=%s -toolkit" % self.installdir)
        else:
            install_interpreter = ""
            install_script = "./cuda-installer"
            # samples are installed in two places with identical copies:
            # self.installdir/samples and $HOME/NVIDIA_CUDA-11.2_Samples
            # changing the second location (the one under $HOME) to a scratch location using
            # --samples --samplespath=self.builddir
            # avoids the duplicate and pollution of the home directory of the installer.
            self.cfg.update('installopts',
                            "--silent --samples --samplespath=%s --toolkit --toolkitpath=%s --defaultroot=%s" % (
                                self.builddir, self.installdir, self.installdir))
            # When eb is called via sudo -u someuser -i eb ..., the installer may try to chown samples to the
            # original user using the SUDO_USER environment variable, which fails
            if "SUDO_USER" in os.environ:
                self.log.info("SUDO_USER was defined as '%s', need to unset it to avoid problems..." %
                              os.environ["SUDO_USER"])
                del os.environ["SUDO_USER"]

        if LooseVersion("10.0") < LooseVersion(self.version) < LooseVersion("10.2") and get_cpu_architecture() == POWER:
            # Workaround for
            # https://devtalk.nvidia.com/default/topic/1063995/cuda-setup-and-installation/cuda-10-1-243-10-1-update-2-ppc64le-run-file-installation-issue/
            install_script = " && ".join([
                "mkdir -p %(installdir)s/targets/ppc64le-linux/include",
                "([ -e %(installdir)s/include ] || ln -s targets/ppc64le-linux/include %(installdir)s/include)",
                "cp -r %(builddir)s/builds/cublas/src %(installdir)s/.",
                install_script
            ]) % {
                'installdir': self.installdir,
                'builddir': self.builddir
            }

        # Use C locale to avoid localized questions and crash on CUDA 10.1
        self.cfg.update('preinstallopts', "export LANG=C && ")

        # As a CUDA recipe gets older and the OS gets updated, it is
        # likely that the system GCC becomes too new for the CUDA version.
        # Since in EasyBuild we know/expect that CUDA will only ever get used
        # as a dependency within the context of a toolchain, we can override
        # the compiler version check that would cause the installation to
        # fail.
        self.cfg.update('installopts', "--override")

        cmd = "%(preinstallopts)s %(interpreter)s %(script)s %(installopts)s" % {
            'preinstallopts': self.cfg['preinstallopts'],
            'interpreter': install_interpreter,
            'script': install_script,
            'installopts': self.cfg['installopts']
        }

        # prepare for running install script autonomously
        qa = [
            # this question is only asked if CUDA tools are already available system-wide
            (r"Would you like to remove all CUDA files under .*\? \(yes/no/abort\): ", "no"),
        ]
        no_qa = [
            r"^Configuring",
            r"Installation Complete",
            r"Verifying archive integrity.*",
            r"^Uncompressing NVIDIA CUDA",
            r".* -> .*",
        ]

        # patch install script to handle Q&A autonomously
        if install_interpreter == "perl":
            patch_perl_script_autoflush(os.path.join(self.builddir, install_script))
            p5lib = os.getenv('PERL5LIB', '')
            if p5lib == '':
                p5lib = self.builddir
            else:
                p5lib = os.pathsep.join([self.builddir, p5lib])
            env.setvar('PERL5LIB', p5lib)

        # make sure $DISPLAY is not defined, which may lead to (weird) problems
        # this is workaround for not being able to specify --nox11 to the Perl install scripts
        if 'DISPLAY' in os.environ:
            os.environ.pop('DISPLAY')

        # cuda-installer creates /tmp/cuda-installer.log (ignoring TMPDIR)
        # Try to remove it before running the installer.
        # This will fail with a usable error if it can't be removed
        # instead of segfaulting in the cuda-installer.
        remove_file('/tmp/cuda-installer.log')

        # overriding qa_timeout default value to 1000 (seconds to wait for nothing to change in the output
        # without seeing a known question)
        run_shell_cmd(cmd, qa_patterns=qa, qa_wait_patterns=no_qa, qa_timeout=1000)

        # Remove the cuda-installer log file
        remove_file('/tmp/cuda-installer.log')

        # check if there are patches to apply
        if len(self.src) > 1:
            for patch in self.src[1:]:
                self.log.debug("Running patch %s", patch['name'])
                run_shell_cmd("/bin/sh " + patch['path'] + " --accept-eula --silent --installdir=" + self.installdir)

    def post_processing_step(self):
        """
        Create wrappers for the specified host compilers, generate the appropriate stub symlinks,
        and create version independent pkgconfig files
        """
        def create_wrapper(wrapper_name, wrapper_comp):
            """Create for a particular compiler, with a particular name"""
            wrapper_f = os.path.join(self.installdir, 'bin', wrapper_name)
            write_file(wrapper_f, WRAPPER_TEMPLATE % wrapper_comp)
            perms = stat.S_IXUSR | stat.S_IRUSR | stat.S_IXGRP | stat.S_IRGRP | stat.S_IXOTH | stat.S_IROTH
            adjust_permissions(wrapper_f, perms)

        # Prepare wrappers to handle a default host compiler other than g++
        for comp in (self.cfg['host_compilers'] or []):
            create_wrapper('nvcc_%s' % comp, comp)

        ldconfig = which('ldconfig', log_ok=False, on_error=IGNORE)
        sbin_dirs = ['/sbin', '/usr/sbin']
        if not ldconfig:
            # ldconfig is usually in /sbin or /usr/sbin
            for cand_path in sbin_dirs:
                if os.path.exists(os.path.join(cand_path, 'ldconfig')):
                    ldconfig = os.path.join(cand_path, 'ldconfig')
                    break

        # fail if we couldn't find ldconfig, because it's really needed
        if ldconfig:
            self.log.info("ldconfig found at %s", ldconfig)
        else:
            path = os.environ.get('PATH', '')
            raise EasyBuildError("Unable to find 'ldconfig' in $PATH (%s), nor in any of %s", path, sbin_dirs)

        stubs_dir = os.path.join(self.installdir, 'lib64', 'stubs')

        # Remove stubs which are not required as the full library is in $EBROOTCUDA/lib64 because this duplication
        # causes issues (e.g. CMake warnings) when using this module (see $LIBRARY_PATH & $LD_LIBRARY_PATH)
        for stub_lib in expand_glob_paths([os.path.join(stubs_dir, '*.*')]):
            real_lib = os.path.join(self.installdir, 'lib64', os.path.basename(stub_lib))
            if os.path.exists(real_lib):
                self.log.debug("Removing unnecessary stub library %s", stub_lib)
                remove_file(stub_lib)
            else:
                self.log.debug("Keeping stub library %s", stub_lib)

        # Run ldconfig to create missing symlinks in the stubs directory (libcuda.so.1, etc)
        cmd = ' '.join([ldconfig, '-N', stubs_dir])
        run_shell_cmd(cmd)

        # GCC searches paths in LIBRARY_PATH and the system paths suffixed with ../lib64 or ../lib first
        # This means stubs/../lib64 is searched before the system /lib64 folder containing a potentially older libcuda.
        # See e.g. https://github.com/easybuilders/easybuild-easyconfigs/issues/12348
        # Workaround: Create a copy that matches this pattern
        new_stubs_dir = os.path.join(self.installdir, 'stubs')
        copy_dir(stubs_dir, os.path.join(new_stubs_dir, 'lib64'), symlinks=True)
        # Also create the lib dir as a symlink
        symlink('lib64', os.path.join(new_stubs_dir, 'lib'), use_abspath_source=False)

        # Packages like xpra look for version independent pc files.
        # See e.g. https://github.com/Xpra-org/xpra/blob/master/setup.py#L206
        # Distros provide these files, so let's do it here too
        pkgconfig_dir = os.path.join(self.installdir, 'pkgconfig')
        if os.path.exists(pkgconfig_dir):
            pc_files = expand_glob_paths([os.path.join(pkgconfig_dir, '*.pc')])
            cwd = change_dir(pkgconfig_dir)
            for pc_file in pc_files:
                pc_file = os.path.basename(pc_file)
                link = re.sub('-[0-9]*.?[0-9]*(.[0-9]*)?.pc', '.pc', pc_file)
                symlink(pc_file, link, use_abspath_source=False)
            change_dir(cwd)

        super(EB_CUDA, self).post_processing_step()

    def sanity_check_step(self):
        """Custom sanity check for CUDA."""

        shlib_ext = get_shared_lib_ext()

        chk_libdir = ["lib64", "lib"]
        culibs = ["cublas", "cudart", "cufft", "curand", "cusparse"]
        custom_paths = {
            'files': [os.path.join("bin", x) for x in ["fatbinary", "nvcc", "nvlink", "ptxas"]] +
            [os.path.join("%s", "lib%s.%s") % (x, y, shlib_ext) for x in chk_libdir for y in culibs],
            'dirs': ["include"],
        }

        # Samples moved to https://github.com/nvidia/cuda-samples
        if LooseVersion(self.version) > LooseVersion('5') and LooseVersion(self.version) < LooseVersion('11.6'):
            custom_paths['files'].append(os.path.join('samples', 'Makefile'))
        if LooseVersion(self.version) < LooseVersion('7'):
            custom_paths['files'].append(os.path.join('open64', 'bin', 'nvopencc'))
        if LooseVersion(self.version) >= LooseVersion('7'):
            custom_paths['files'].append(os.path.join("extras", "CUPTI", "lib64", "libcupti.%s") % shlib_ext)
            custom_paths['dirs'].append(os.path.join("extras", "CUPTI", "include"))

        # Just a subset of files are checked, since the whole list is likely to change,
        # and irrelevant in most cases anyway
        if os.path.exists(os.path.join(self.installdir, 'pkgconfig')):
            pc_files = ['cublas.pc', 'cudart.pc', 'cuda.pc']
            custom_paths['files'].extend(os.path.join('pkgconfig', x) for x in pc_files)

        super(EB_CUDA, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Set the install directory as CUDA_HOME, CUDA_ROOT, CUDA_PATH."""

        # avoid adding of installation directory to $PATH (cfr. Binary easyblock) since that may cause trouble,
        # for example when there's a clash between command name and a subdirectory in the installation directory
        # (like compute-sanitizer)
        self.cfg['prepend_to_path'] = False

        txt = super(EB_CUDA, self).make_module_extra()
        txt += self.module_generator.set_environment('CUDA_HOME', self.installdir)
        txt += self.module_generator.set_environment('CUDA_ROOT', self.installdir)
        txt += self.module_generator.set_environment('CUDA_PATH', self.installdir)
        self.log.debug("make_module_extra added this: %s", txt)
        return txt
