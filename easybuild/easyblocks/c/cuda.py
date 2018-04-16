##
# This file is an EasyBuild reciPY as per https://github.com/easybuilders/easybuild
#
# Copyright:: Copyright 2012-2018 Cyprus Institute / CaSToRC, Uni.Lu, NTUA, Ghent University, Forschungszentrum Juelich GmbH
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
"""
import os
import stat

from distutils.version import LooseVersion

from easybuild.easyblocks.generic.binary import Binary
from easybuild.framework.easyconfig import CUSTOM
from easybuild.tools.filetools import adjust_permissions, patch_perl_script_autoflush, write_file
from easybuild.tools.run import run_cmd, run_cmd_qa
from easybuild.tools.systemtools import get_shared_lib_ext

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
            install_script = "install-linux.pl"
            self.cfg.update('installopts', '--prefix=%s' % self.installdir)
        else:
            install_script = "cuda-installer.pl"
            # note: also including samples (via "-samplespath=%(installdir)s -samples") would require libglut
            self.cfg.update('installopts', "-verbose -silent -toolkitpath=%s -toolkit" % self.installdir)

        cmd = "%(preinstallopts)s perl ./%(script)s %(installopts)s" % {
            'preinstallopts': self.cfg['preinstallopts'],
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
        patch_perl_script_autoflush(os.path.join(self.builddir, install_script))

        # make sure $DISPLAY is not defined, which may lead to (weird) problems
        # this is workaround for not being able to specify --nox11 to the Perl install scripts
        if 'DISPLAY' in os.environ:
            os.environ.pop('DISPLAY')

        #overriding maxhits default value to 300 (300s wait for nothing to change in the output without seeing a known question)
        run_cmd_qa(cmd, qanda, std_qa=stdqa, no_qa=noqanda, log_all=True, simple=True, maxhits=300)

    def post_install_step(self):
        """Create wrappers for the specified host compilers"""
        def create_wrapper(wrapper_name, wrapper_comp):
            """Create for a particular compiler, with a particular name"""
            wrapper_f = os.path.join(self.installdir, 'bin', wrapper_name)
            write_file(wrapper_f, WRAPPER_TEMPLATE % wrapper_comp)
            adjust_permissions(wrapper_f, stat.S_IXUSR|stat.S_IRUSR|stat.S_IXGRP|stat.S_IRGRP|stat.S_IXOTH|stat.S_IROTH)

        # Prepare wrappers to handle a default host compiler other than g++
        for comp in (self.cfg['host_compilers'] or []):
            create_wrapper('nvcc_%s' % comp, comp)

        super(EB_CUDA, self).post_install_step()

    def sanity_check_step(self):
        """Custom sanity check for CUDA."""
        shlib_ext = get_shared_lib_ext()

        chk_libdir = ["lib64"]

        # Versions higher than 6 do not provide 32 bit libraries
        if LooseVersion(self.version) < LooseVersion("6"):
            chk_libdir += ["lib"]

        custom_paths = {
            'files': ["bin/%s" % x for x in ["fatbinary", "nvcc", "nvlink", "ptxas"]] +
                     ["%s/lib%s.%s" % (x, y, shlib_ext) for x in chk_libdir for y in ["cublas", "cudart", "cufft",
                                                                                      "curand", "cusparse"]],
            'dirs': ["include"],
        }

        if LooseVersion(self.version) < LooseVersion('7'):
            custom_paths['files'].append('open64/bin/nvopencc')
        if LooseVersion(self.version) >= LooseVersion('7'):
            custom_paths['files'].append("extras/CUPTI/lib64/libcupti.%s" % shlib_ext)
            custom_paths['dirs'].append("extras/CUPTI/include")


        super(EB_CUDA, self).sanity_check_step(custom_paths=custom_paths)

    def make_module_req_guess(self):
        """Specify CUDA custom values for PATH etc."""

        guesses = super(EB_CUDA, self).make_module_req_guess()

        # The dirs should be in the order ['open64/bin', 'bin']
        bin_path = []
        if LooseVersion(self.version) < LooseVersion('7'):
            bin_path.append('open64/bin')
        bin_path.append('bin')

        lib_path = ['lib64']
        inc_path = ['include']
        if LooseVersion(self.version) >= LooseVersion('7'):
            lib_path.append('extras/CUPTI/lib64')
            inc_path.append('extras/CUPTI/include')

        guesses.update({
            'PATH': bin_path,
            'LD_LIBRARY_PATH': lib_path,
            'CPATH': inc_path,
            'CUDA_HOME': [''],
            'CUDA_ROOT': [''],
            'CUDA_PATH': [''],
        })

        return guesses
