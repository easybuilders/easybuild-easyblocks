from easybuild.easyblocks.generic.configuremake import ConfigureMake
from easybuild.tools.systemtools import X86_64, get_cpu_architecture, get_shared_lib_ext


class EB_libdrm(ConfigureMake):
    """
    Support for building libdrm on different architectures
    """

    def sanity_check_step(self):
        """Custom sanity check for libdrm"""
        shlib_ext = get_shared_lib_ext()
        custom_paths = {
            'files': ['include/xf86drm.h', 'include/xf86drmMode.h',
                      'lib/libdrm_radeon.%s' % shlib_ext, 'lib/libdrm.%s' % shlib_ext, 'lib/libkms.%s' % shlib_ext],
            'dirs': ['include/libdrm', 'include/libkms', 'lib/pkgconfig'],
        }

        arch = get_cpu_architecture()
        if arch == X86_64:
            custom_paths['files'].append('lib/libdrm_intel.%s' % shlib_ext)

        super(EB_libdrm, self).sanity_check_step(custom_paths=custom_paths)
