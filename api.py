from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import yaml
import os
from services.image_search import ImageSearch
from config.settings import Config

app = FastAPI(title="VVQuest API")

# 初始化核心组件
config = Config()
search_engine = ImageSearch(mode='api', model_name=config.models.default_model)

# 数据模型定义
class SearchRequest(BaseModel):
    query: str
    n_results: int = 5

class ConfigUpdate(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None

class ModelDownloadRequest(BaseModel):
    model_id: str

# API 端点
@app.post("/search")
async def search_images(request: SearchRequest):
    """执行图片搜索"""
    try:
        results = search_engine.search(
            request.query,
            request.n_results,
            config.api.embedding_models.api_key
        )
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate-cache")
async def generate_cache(background_tasks: BackgroundTasks):
    """触发缓存生成（后台任务）"""
    if not search_engine.has_cache():
        background_tasks.add_task(search_engine.generate_cache)
        return {"message": "Cache generation started"}
    return {"message": "Cache already exists"}

@app.get("/config")
async def get_config():
    """获取当前配置"""
    return {
        "mode": search_engine.mode,
        "model": search_engine.model_name,
        "api_key": config.api.embedding_models.api_key,
        "base_url": config.api.embedding_models.base_url
    }

@app.put("/config")
async def update_config(update: ConfigUpdate):
    """更新API配置"""
    try:
        if update.api_key:
            config.api.embedding_models.api_key = update.api_key
        if update.base_url:
            config.api.embedding_models.base_url = update.base_url
        config.save()
        return {"message": "Config updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download-model")
async def download_model(req: ModelDownloadRequest):
    """下载指定模型"""
    try:
        if search_engine.embedding_service.is_model_downloaded(req.model_id):
            return {"message": "Model already exists"}
        
        search_engine.download_model(req.model_id)
        return {"message": "Model download completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/models")
async def list_models():
    """获取可用模型列表"""
    models = []
    for model_id, info in Config().models.embedding_models.items():
        models.append({
            "id": model_id,
            "performance": info.performance,
            "downloaded": search_engine.embedding_service.is_model_downloaded(model_id)
        })
    return {"models": models}

@app.put("/mode/{mode}")
async def switch_mode(mode: str):
    """切换运行模式"""
    if mode not in ['api', 'local']:
        raise HTTPException(status_code=400, detail="Invalid mode")
    
    try:
        search_engine.set_mode(mode)
        return {"message": f"Switched to {mode} mode"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/model/{model_id}")
async def switch_model(model_id: str):
    """切换本地模型（修复版）"""
    try:
        # 增加模式验证
        if search_engine.mode != 'local':
            raise HTTPException(
                status_code=400, 
                detail="必须先切换到本地模式再切换模型"
            )

        # 验证模型是否存在
        if model_id not in Config().models.embedding_models:
            raise HTTPException(
                status_code=404,
                detail=f"模型 {model_id} 未在配置中定义"
            )

        # 验证模型文件
        if not search_engine.embedding_service.is_model_downloaded(model_id):
            raise HTTPException(
                status_code=412,  # 前置条件失败
                detail=f"模型 {model_id} 尚未下载"
            )

        # 增加设备检测
        device = "cuda" if torch.cuda.is_available() else "cpu"
        search_engine.embedding_service.device = device

        # 执行切换（增加显存清理）
        with torch.no_grad():
            torch.cuda.empty_cache()  # 清理显存
            search_engine.set_mode('local', model_id)

        return {"message": f"成功切换到模型 {model_id} (device: {device})"}
    
    except HTTPException as he:
        raise he  # 传递已处理的错误
    except Exception as e:
        import traceback
        traceback.print_exc()  # 打印完整堆栈
        raise HTTPException(
            status_code=500,
            detail=f"模型加载失败: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)