##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2019 Cyprus Institute / CaSToRC, Uni.Lu, NTUA, Ghent University, Forschungszentrum Juelich GmbH
# Authors::   George Tsouloupas <g.tsouloupas@cyi.ac.cy>, Fotis Georgatos <fotis@cern.ch>, Kenneth Hoste, Damian Alvarez
# License::   MIT/GPL
# $Id$
#
# This work implements a part of the HPCBIOS project and is a component of the policy:
# http://hpcbios.readthedocs.org/en/latest/HPCBIOS_2012-99.html
##
"""
EasyBuild support for CUDA, implemented as an easyblock

Ref: https://speakerdeck.com/ajdecon/introduction-to-the-cuda-toolkit-for-building-applications

@author: George Tsouloupas (Cyprus Institute)
@author: Fotis Georgatos (Uni.lu)
@author: Kenneth Hoste (Ghent University)
@author: Damian Alvarez (Forschungszentrum Juelich)
@author: Ward Poelmans (Free University of Brussels)
"""
import os
import re
import stat

from distutils.version import LooseVersion

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.filetools import adjust_permissions, patch_perl_script_autoflush, read_file, which, write_file
from easybuild.tools.run import run_cmd, run_cmd_qa
from easybuild.tools.systemtools import POWER, X86_64, get_cpu_architecture, get_shared_lib_ext

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
        if myarch == X86_64:
            cudaarch = ''
        elif myarch == POWER:
            cudaarch = '_ppc64le'
        else:
            raise EasyBuildError("Architecture %s is not supported for CUDA on EasyBuild", myarch)

        super(EB_CUDA, self).__init__(*args, **kwargs)

        self.cfg.template_values['cudaarch'] = cudaarch
        self.cfg.generate_template_values()

    def extract_step(self):
        """Extract installer to have more control, e.g. options, patching Perl scripts, etc."""
        execpath = self.src[0]['path']
        run_cmd("/bin/sh " + execpath + " --noexec --nox11 --target " + self.builddir)
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
            # note: also including samples (via "-samplespath=%(installdir)s -samples") would require libglut
            self.cfg.update('installopts', "-verbose -silent -toolkitpath=%s -toolkit" % self.installdir)
        else:
            install_interpreter = ""
            install_script = "./cuda-installer"
            # note: also including samples (via "-samplespath=%(installdir)s -samples") would require libglut
            self.cfg.update('installopts', "--silent --toolkit --toolkitpath=%s --defaultroot=%s" % (
                            self.installdir, self.installdir))

        cmd = "%(preinstallopts)s %(interpreter)s %(script)s %(installopts)s" % {
            'preinstallopts': self.cfg['preinstallopts'],
            'interpreter': install_interpreter,
            'script': install_script,
            'installopts': self.cfg['installopts']
        }

        # prepare for running install script autonomously
        qanda = {}
        stdqa = {
            # this question is only asked if CUDA tools are already available system-wide
            r"Would you like to remove all CUDA files under .*? (yes/no/abort): ": "no",
        }
        noqanda = [
            r"^Configuring",
            r"Installation Complete",
            r"Verifying archive integrity.*",
            r"^Uncompressing NVIDIA CUDA",
            r".* -> .*",
        ]

        # patch install script to handle Q&A autonomously
        if install_interpreter == "perl":
            patch_perl_script_autoflush(os.path.join(self.builddir, install_script))

        # make sure $DISPLAY is not defined, which may lead to (weird) problems
        # this is workaround for not being able to specify --nox11 to the Perl install scripts
        if 'DISPLAY' in os.environ:
            os.environ.pop('DISPLAY')

        # overriding maxhits default value to 300 (300s wait for nothing to change in the output without seeing a known
        # question)
        run_cmd_qa(cmd, qanda, std_qa=stdqa, no_qa=noqanda, log_all=True, simple=True, maxhits=300)

        # check if there are patches to apply
        if len(self.src) > 1:
            for patch in self.src[1:]:
                self.log.debug("Running patch %s", patch['name'])
                run_cmd("/bin/sh " + patch['path'] + " --accept-eula --silent --installdir=" + self.installdir)

    def post_install_step(self):
        """Create wrappers for the specified host compilers and generate the appropriate stub symlinks"""
        def create_wrapper(wrapper_name, wrapper_comp):
            """Create for a particular compiler, with a particular name"""
            wrapper_f = os.path.join(self.installdir, 'bin', wrapper_name)
            write_file(wrapper_f, WRAPPER_TEMPLATE % wrapper_comp)
            perms = stat.S_IXUSR | stat.S_IRUSR | stat.S_IXGRP | stat.S_IRGRP | stat.S_IXOTH | stat.S_IROTH
            adjust_permissions(wrapper_f, perms)

        # Prepare wrappers to handle a default host compiler other than g++
        for comp in (self.cfg['host_compilers'] or []):
            create_wrapper('nvcc_%s' % comp, comp)

        ldconfig = which('ldconfig')
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

        # Run ldconfig to create missing symlinks in the stubs directory (libcuda.so.1, etc)
        cmd = ' '.join([ldconfig, '-N', os.path.join(self.installdir, 'lib64', 'stubs')])
        run_cmd(cmd)

        super(EB_CUDA, self).post_install_step()

    def sanity_check_step(self):
        """Custom sanity check for CUDA."""

        if LooseVersion(self.version) > LooseVersion("9"):
            versionfile = read_file(os.path.join(self.installdir, "version.txt"))
            if not re.search("Version %s$" % self.version, versionfile):
                raise EasyBuildError("Unable to find the correct version (%s) in the version.txt file", self.version)

        shlib_ext = get_shared_lib_ext()

        chk_libdir = ["lib64"]

        # Versions higher than 6 do not provide 32 bit libraries
        if LooseVersion(self.version) < LooseVersion("6"):
            chk_libdir += ["lib"]

        culibs = ["cublas", "cudart", "cufft", "curand", "cusparse"]
        custom_paths = {
            'files': [os.path.join("bin", x) for x in ["fatbinary", "nvcc", "nvlink", "ptxas"]] +
            [os.path.join("%s", "lib%s.%s") % (x, y, shlib_ext) for x in chk_libdir for y in culibs],
            'dirs': ["include"],
        }

        if LooseVersion(self.version) < LooseVersion('7'):
            custom_paths['files'].append(os.path.join('open64', 'bin', 'nvopencc'))
        if LooseVersion(self.version) >= LooseVersion('7'):
            custom_paths['files'].append(os.path.join("extras", "CUPTI", "lib64", "libcupti.%s") % shlib_ext)
            custom_paths['dirs'].append(os.path.join("extras", "CUPTI", "include"))

        super(EB_CUDA, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_extra(self):
        """Set the install directory as CUDA_HOME, CUDA_ROOT, CUDA_PATH."""
        txt = super(EB_CUDA, self).make_module_extra()
        txt += self.module_generator.set_environment('CUDA_HOME', self.installdir)
        txt += self.module_generator.set_environment('CUDA_ROOT', self.installdir)
        txt += self.module_generator.set_environment('CUDA_PATH', self.installdir)
        self.log.debug("make_module_extra added this: %s", txt)
        return txt

    def make_module_req_guess(self):
        """Specify CUDA custom values for PATH etc."""

        guesses = super(EB_CUDA, self).make_module_req_guess()

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

        guesses.update({
            'PATH': bin_path,
            'LD_LIBRARY_PATH': lib_path,
            'LIBRARY_PATH': ['lib64', os.path.join('lib64', 'stubs')],
            'CPATH': inc_path,
        })

        return guesses
