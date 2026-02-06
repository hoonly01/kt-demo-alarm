import fitz  # PyMuPDF
import os

def convert_pdf_pages_to_images(pdf_path, output_dir="pdf_to_images"):
    """PDF 파일의 모든 페이지를 이미지로 변환하여 저장합니다."""
    
    # 출력 폴더가 없으면 생성
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    # PDF 파일 열기
    doc = fitz.open(pdf_path)
    
    print(f"총 {len(doc)} 페이지의 변환을 시작합니다...")

    # 모든 페이지를 순회하며 이미지로 저장
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)  # 페이지 로드
        
        # 1. 페이지를 이미지 픽셀맵으로 렌더링
        pix = page.get_pixmap(dpi=300)
        
        # 2. 이미지 파일 경로 설정 (page_1.png, page_2.png, ...)
        image_path = os.path.join(output_dir, f"page_{page_num + 1}.png")
        
        # 3. 이미지 파일로 저장
        pix.save(image_path)
        
        print(f"✅ 페이지 {page_num + 1} 저장 완료: {image_path}")

    doc.close()
    print("\n모든 페이지의 이미지 변환이 완료되었습니다.")
