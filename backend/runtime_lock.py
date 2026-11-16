from contextlib import contextmanager


@contextmanager
def execution_lease(path):
    """Prevent two local server instances from operating the same live data directory."""
    import os
    handle=open(path,'a+b')
    try:
        handle.seek(0)
        if handle.read(1)==b'':
            handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError('Another live execution session owns this data directory')
    try:yield
    finally:handle.close()
