import objc
from Foundation import NSURL
import Vision
import Quartz
from typing import List, Dict, Optional
import os
import time
import logging

logger = logging.getLogger(__name__)

class AppleVisionOCR:
    """
    Wrapper for Apple's Vision Framework to perform local OCR on macOS.
    This is ultra-fast, offline, and does not consume API quota.
    """
    
    @staticmethod
    def extract_text_from_image(image_path: str) -> Optional[str]:
        """
        Extracts raw text from an image file using VNRecognizeTextRequest.
        """
        if not os.path.exists(image_path):
            logger.error(f"Image path not found: {image_path}")
            return None

        try:
            # 1. Load image via Quartz (Core Graphics)
            input_url = NSURL.fileURLWithPath_(image_path)
            image_source = Quartz.CGImageSourceCreateWithURL(input_url, None)
            cg_image = Quartz.CGImageSourceCreateImageAtIndex(image_source, 0, None)
            
            if not cg_image:
                logger.error("Failed to create CGImage from source.")
                return None

            # 2. Prepare Vision request
            results = []

            def handler(request, error):
                if error:
                    logger.error(f"OCR Request Error: {error}")
                    return
                
                observations = request.results()
                for observation in observations:
                    # Get top candidate string
                    top_candidate = observation.topCandidates_(1)[0]
                    results.append(top_candidate.string())

            request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)
            request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
            request.setUsesLanguageCorrection_(True)

            # 3. Execute request
            image_handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg_image, None)
            success, error = image_handler.performRequests_error_([request], None)

            if not success:
                logger.error(f"Vision Request Failed: {error}")
                return None

            full_text = "\n".join(results)
            return full_text

        except Exception as e:
            logger.error(f"Vision OCR processing failed: {e}")
            return None

if __name__ == "__main__":
    # Unit Test logic
    import sys
    if len(sys.argv) > 1:
        test_path = sys.argv[1]
        start_time = time.time()
        text = AppleVisionOCR.extract_text_from_image(test_path)
        duration = (time.time() - start_time) * 1000
        
        print("\n--- OCR TEST RESULT ---")
        print(f"Path: {test_path}")
        print(f"Duration: {duration:.1f}ms")
        print("--- TEXT ---")
        print(text)
        print("-----------------------\n")
    else:
        print("Usage: python3 src/utils/local_ocr.py [path_to_image]")
