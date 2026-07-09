import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

# 1. Ayarlar ve Güvenlik
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")
if api_key:
    print(f"✅ API Anahtarı başarıyla yüklendi.") 
else:
    print("❌ HATA: API Anahtarı hala okunamıyor! .env dosyasını kontrol et.")
app = FastAPI(title="KVKK Hukuk Asistanı API")

# 2. Modellerin ve Veritabanının Başlatılması (Hücre 1 & 5)
print("⏳ Modeller ve Veritabanı yükleniyor...")

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

llm = ChatGroq(
    temperature=0.1, 
    model_name="llama-3.3-70b-versatile"
)

# Kaggle'dan indirilen klasör yolu
vektor_veritabani = Chroma(
    persist_directory="./kvkk_chroma_db_v2", 
    embedding_function=embeddings
)
print(f"📊 Veritabanındaki toplam doküman (chunk) sayısı: {vektor_veritabani._collection.count()}")

# 3. Senin Özel Prompt Şablonun (Hücre 5)
prompt_sablonu = ChatPromptTemplate.from_messages([
    ("system", """Sen uzman, yardımcı, profesyonel bir Türk Hukuku asistanısın. YALNIZCA HUKUK alanında gelen soruları yanıtlayabiliyorsun. HUKUK dışında hiçbir sorunun cevabını vermiyorsun ve bu tarz sorularda cevap olarak 'Üzgünüm, hukuk dışı konular hakkında bilgilendirme yapamamaktayım. ' de ve sus.
    
    KURALLAR:
    1. Öncelikle aşağıda 'BAĞLAM' başlığı altında sağlanan hukuki metinleri incele.
    2. Eğer cevap bağlamda varsa, veritabanına sadık kalarak maddeleyerek cevapla.
    3. Eğer soru genel bir hukuki (örneğin 'KVKK nedir?') bağlamda yoksa; SADECE VE YALNIZCA kendi KVKK hukuk bilgilerini kullanarak  cevap ver.
    4. Proje çalınması gibi durumlarda genel hukuk yollarını (ihtarname, tespit davası vb.) açıkla.
    5. Asla hukuk dışı soruları yanıtlama. 
    6. Cevapların her zaman ciddi, profesyonel ve hukuk diline uygun olsun.
    
    BAĞLAM:
    {baglam}"""),
    ("human", "{soru}")
])

print("✅ Sistem Hazır!")

# 4. Veri Modelleri
class SoruModeli(BaseModel):
    soru_metni: str

# 5. API Endpoint (Chat Mantığı)
@app.post("/soru-sor")
def chatbot_cevapla(soru: SoruModeli):
    try:
        print(f"\n[1] Soru alındı: {soru.soru_metni}")
        
        print("[2] Vektör veritabanında arama yapılıyor...")
        sonuclar = vektor_veritabani.similarity_search_with_score(soru.soru_metni, k=5)
        
        baglam_metni = ""
        kaynak_linkleri = set()
        bulunan_kaynaklar = []
        for i, (sonuc, skor) in enumerate(sonuclar):
            baglam_metni += f"\n--- Metin {i+1} ---\n{sonuc.page_content}\n"
            link = sonuc.metadata.get("source_link", "")
            kaynak_adi = sonuc.metadata.get("source", "Bilinmiyor")
            
            if link and link != "Link Yok":
                kaynak_linkleri.add(link)
            bulunan_kaynaklar.append({
                "sira": i + 1,
                "kaynak": kaynak_adi,
                "benzerlik_skoru": round(float(skor), 4),
                "metin_ozeti": sonuc.page_content[:100] + "...",
                "link": link or "Link Yok"
            })
            print(f"  📄 Chunk {i+1}: '{kaynak_adi}' | Skor: {skor:.4f} | {sonuc.page_content[:60]}...")

        en_iyi_skor = sonuclar[0][1] if sonuclar else 999

        if en_iyi_skor < 6.0:
            veritabanindan_mi = True
            kaynak_etiketi = "✅ VERİTABANI"
        elif en_iyi_skor < 9.0:
            veritabanindan_mi = True
            kaynak_etiketi = "⚠️ VERİTABANI (zayıf eşleşme)"
        else:
            veritabanindan_mi = False
            kaynak_etiketi = "❌ GROQ KENDİ BİLGİSİ"

        print(f"[3] {len(kaynak_linkleri)} kaynak bulundu. En iyi benzerlik skoru: {en_iyi_skor:.4f}")
        print(f"[3b] Cevap kaynağı: {kaynak_etiketi}")

        zincir = prompt_sablonu | llm
        cevap = zincir.invoke({"baglam": baglam_metni, "soru": soru.soru_metni})
        print("[4] Groq'tan cevap başarıyla alındı.")
        return {
            "cevap": cevap.content,
            "kaynaklar": list(kaynak_linkleri),
            "debug": {
                "veritabanindan_mi": veritabanindan_mi,
                "en_iyi_skor": round(float(en_iyi_skor), 4),
                "bulunan_chunklar": bulunan_kaynaklar
            }
        }
    except Exception as e:
        print(f"\n[!] HATA OLUŞTU: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)