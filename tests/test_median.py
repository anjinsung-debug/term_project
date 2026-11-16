import unittest
import numpy as np
import cv2
from pacs.algorithms.median import apply

class MedianTests(unittest.TestCase):
    def test_impulse_noise(self):
        img=np.full((7,7),100,dtype=np.uint8)
        img[2,2]=255
        img[4,4]=0
        np.testing.assert_array_equal(apply(img), np.full((7,7),100,dtype=np.uint8))

    def test_reference_and_preservation(self):
        img=np.random.default_rng(42).integers(0,256,(11,12),dtype=np.uint8)
        before=img.copy()
        for size in (3,5,7,9):
            with self.subTest(size=size):
                padded=np.pad(img,size//2,mode='edge')
                windows=np.lib.stride_tricks.sliding_window_view(padded,(size,size))
                expected=np.median(windows,axis=(-2,-1)).astype(np.uint8)
                out=apply(img,size)
                np.testing.assert_array_equal(out,expected)
                np.testing.assert_array_equal(img,before)
                self.assertEqual(out.dtype,np.uint8)
                self.assertEqual(out.shape,img.shape)
                self.assertFalse(np.shares_memory(img,out))

    def test_bad_images(self):
        for img in (None,[],np.zeros((3,3,3),dtype=np.uint8),np.zeros((3,3)),np.zeros((0,3),dtype=np.uint8)):
            with self.subTest(image=type(img)), self.assertRaises(ValueError): apply(img)

    def test_bad_sizes(self):
        img=np.zeros((9,9),dtype=np.uint8)
        for size in (True,np.bool_(True),None,'3',3.0,3.5,0,1,2,4,10,11,float('nan'),float('inf')):
            with self.subTest(size=size), self.assertRaises(ValueError): apply(img,size)

    def test_numpy_integer(self):
        img=np.zeros((5,5),dtype=np.uint8)
        np.testing.assert_array_equal(apply(img,np.int64(3)),img)

    def test_noncontiguous_input(self):
        img=np.arange(100,dtype=np.uint8).reshape(10,10)[:,::2]
        np.testing.assert_array_equal(apply(img),apply(img.copy()))

if __name__=='__main__':
    print('OpenCV',cv2.__version__)
    unittest.main(verbosity=2)


