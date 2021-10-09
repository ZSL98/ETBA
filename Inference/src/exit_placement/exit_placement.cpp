/*
Exit placement
*/

#include <cuda_runtime.h>
#include "exit_placement.h"

Profiler::Profiler(
const size_t& batch_size_s1, const size_t& batch_size_s2,
 const int batch_num, const Severity severity)
: batch_size_s1_(batch_size_s1), batch_size_s2_(batch_size_s2), batch_num_(batch_num)
{
    cudaStreamCreate(&(stream_));
    CUDACHECK(cudaEventCreate(&infer_start));
    CUDACHECK(cudaEventCreate(&s1_end));
    CUDACHECK(cudaEventCreate(&s2_end));
    sample::gLogger.setReportableSeverity(severity);
}

bool Profiler::build_s0()
{
    auto builder = TRTUniquePtr<nvinfer1::IBuilder>(nvinfer1::createInferBuilder(sample::gLogger.getTRTLogger()));
    if (!builder) {
        std::cout << "Failed to create S0 builder";
        return false;
    }
    const auto explicit_batch = 1U << static_cast<uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
    auto network = TRTUniquePtr<nvinfer1::INetworkDefinition>(builder->createNetworkV2(explicit_batch));
    if (!network) {
        std::cout << "Failed to create S0 network";
        return false;
    }
    auto config = TRTUniquePtr<nvinfer1::IBuilderConfig>(builder->createBuilderConfig());
    if (!config) {
        return false;
    }

    auto parser = TRTUniquePtr<nvonnxparser::IParser>(nvonnxparser::createParser(*network, sample::gLogger.getTRTLogger()));
    if (!parser) {
        std::cout << "Failed to create S0 parser";
        return false;
    }

    auto constructed = construct_s0(builder, network, config, parser);
    if (!constructed) {
        std::cout << "Failed to construct S0 network";
        return false;
    }

    mEngine_s0 = std::shared_ptr<nvinfer1::ICudaEngine>(builder->buildEngineWithConfig(*network, *config), samplesCommon::InferDeleter());
    if (!mEngine_s0) {
        std::cout << "Failed to create S0 engine";
        return false;
    }

    mContext_s0 = std::shared_ptr<nvinfer1::IExecutionContext>(mEngine_s0->createExecutionContext(), samplesCommon::InferDeleter());
    return true;
}

bool Profiler::build_s1()
{
    auto builder = TRTUniquePtr<nvinfer1::IBuilder>(nvinfer1::createInferBuilder(sample::gLogger.getTRTLogger()));
    if (!builder) {
        std::cout << "Failed to create S1 builder";
        return false;
    }
    const auto explicit_batch = 1U << static_cast<uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
    auto network = TRTUniquePtr<nvinfer1::INetworkDefinition>(builder->createNetworkV2(explicit_batch));
    if (!network) {
        std::cout << "Failed to create S1 network";
        return false;
    }
    auto config = TRTUniquePtr<nvinfer1::IBuilderConfig>(builder->createBuilderConfig());
    if (!config) {
        return false;
    }

    auto parser = TRTUniquePtr<nvonnxparser::IParser>(nvonnxparser::createParser(*network, sample::gLogger.getTRTLogger()));
    if (!parser) {
        std::cout << "Failed to create S1 parser";
        return false;
    }

    auto constructed = construct_s1(builder, network, config, parser);
    if (!constructed) {
        std::cout << "Failed to construct S1 network";
        return false;
    }

    mEngine_s1 = std::shared_ptr<nvinfer1::ICudaEngine>(builder->buildEngineWithConfig(*network, *config), samplesCommon::InferDeleter());
    if (!mEngine_s1) {
        std::cout << "Failed to create S1 engine";
        return false;
    }

    mContext_s1 = std::shared_ptr<nvinfer1::IExecutionContext>(mEngine_s1->createExecutionContext(), samplesCommon::InferDeleter());
    return true;
}

bool Profiler::build_s2()
{
    auto builder = TRTUniquePtr<nvinfer1::IBuilder>(nvinfer1::createInferBuilder(sample::gLogger.getTRTLogger()));
    if (!builder) {
        std::cout << "Failed to create S2 builder";
        return false;
    }

    const auto explicit_batch = 1U << static_cast<uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
    auto network = TRTUniquePtr<nvinfer1::INetworkDefinition>(builder->createNetworkV2(explicit_batch));
    if (!network) {
        std::cout << "Failed to create S2 network";
        return false;
    }

    auto config = TRTUniquePtr<nvinfer1::IBuilderConfig>(builder->createBuilderConfig());
    if (!config) {
        return false;
    }

    auto parser = TRTUniquePtr<nvonnxparser::IParser>(nvonnxparser::createParser(*network, sample::gLogger.getTRTLogger()));
    if (!parser) {
        std::cout << "Failed to create S2 parser";
        return false;
    }

    auto constructed = construct_s2(builder, network, config, parser);
    if (!constructed) {
        std::cout << "Failed to construct S2 network";
        return false;
    }

    mEngine_s2 = std::shared_ptr<nvinfer1::ICudaEngine>(builder->buildEngineWithConfig(*network, *config), samplesCommon::InferDeleter());
    if (!mEngine_s2) {
        std::cout << "Failed to create S2 engine";
        return false;
    }

    mContext_s2 = std::shared_ptr<nvinfer1::IExecutionContext>(mEngine_s2->createExecutionContext(), samplesCommon::InferDeleter());
    return true;
}

bool Profiler::construct_s0(
    TRTUniquePtr<nvinfer1::IBuilder>& builder,
    TRTUniquePtr<nvinfer1::INetworkDefinition>& network,
    TRTUniquePtr<nvinfer1::IBuilderConfig>& config,
    TRTUniquePtr<nvonnxparser::IParser>& parser)
{
    auto profile = builder->createOptimizationProfile();
    samplesCommon::OnnxSampleParams params;
    params.dataDirs.emplace_back("/home/slzhang/projects/ETBA/Inference/src/exit_placement/models");
    //data_dir.push_back("samples/VGG16/");
    auto parsed = parser->parseFromFile(locateFile("resnet101.onnx", params.dataDirs).c_str(),
    static_cast<int>(sample::gLogger.getReportableSeverity()));
    if (!parsed) {
        return false;
    }

    input_dims_s0 = network->getInput(0)->getDimensions();
    input_tensor_names_ = network->getInput(0)->getName();

    nvinfer1::Dims min_dims = input_dims_s0;
    min_dims.d[0] = batch_size_s1_;
    nvinfer1::Dims opt_dims = input_dims_s0;
    opt_dims.d[0] = batch_size_s1_;
    nvinfer1::Dims max_dims = input_dims_s0;
    max_dims.d[0] = batch_size_s1_;

    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kMIN, min_dims);
    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kOPT, opt_dims);
    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kMAX, max_dims);

    config->addOptimizationProfile(profile);
    config->setMaxWorkspaceSize(3_GiB);
    return true;
}

bool Profiler::construct_s1(
    TRTUniquePtr<nvinfer1::IBuilder>& builder,
    TRTUniquePtr<nvinfer1::INetworkDefinition>& network,
    TRTUniquePtr<nvinfer1::IBuilderConfig>& config,
    TRTUniquePtr<nvonnxparser::IParser>& parser)
{
    auto profile = builder->createOptimizationProfile();
    samplesCommon::OnnxSampleParams params;
    params.dataDirs.emplace_back("/home/slzhang/projects/ETBA/Inference/src/exit_placement/models");
    //data_dir.push_back("samples/VGG16/");
    auto parsed = parser->parseFromFile(locateFile("unipose_s1.onnx", params.dataDirs).c_str(),
    static_cast<int>(sample::gLogger.getReportableSeverity()));
    if (!parsed) {
        return false;
    }

    input_dims_s1 = network->getInput(0)->getDimensions();
    input_tensor_names_ = network->getInput(0)->getName();

    nvinfer1::Dims min_dims = input_dims_s1;
    min_dims.d[0] = batch_size_s1_;
    nvinfer1::Dims opt_dims = input_dims_s1;
    opt_dims.d[0] = batch_size_s1_;
    nvinfer1::Dims max_dims = input_dims_s1;
    max_dims.d[0] = batch_size_s1_;

    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kMIN, min_dims);
    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kOPT, opt_dims);
    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kMAX, max_dims);

    config->addOptimizationProfile(profile);
    config->setMaxWorkspaceSize(3_GiB);
    // config->setMinTimingIterations(2);
    // config->setAvgTimingIterations(1);
    // std::cout << "getMinTimingIterations: " << config->getMinTimingIterations() << std::endl;
    // std::cout << "getAvgTimingIterations: " << config->getAvgTimingIterations() << std::endl;
    return true;
}

bool Profiler::construct_s2(
    TRTUniquePtr<nvinfer1::IBuilder>& builder,
    TRTUniquePtr<nvinfer1::INetworkDefinition>& network,
    TRTUniquePtr<nvinfer1::IBuilderConfig>& config,
    TRTUniquePtr<nvonnxparser::IParser>& parser)
{
    auto profile = builder->createOptimizationProfile();
    samplesCommon::OnnxSampleParams params;
    params.dataDirs.emplace_back("/home/slzhang/projects/ETBA/Inference/src/exit_placement/models");
    //data_dir.push_back("samples/VGG16/");
    auto parsed = parser->parseFromFile(locateFile("unipose_s2.onnx", params.dataDirs).c_str(),
    static_cast<int>(sample::gLogger.getReportableSeverity()));
    if (!parsed) {
        return false;
    }

    input_dims_s2 = network->getInput(0)->getDimensions();
    // std::cout << "Channel num: " << input_dims_s2.d[1] << std::endl;
    input_tensor_names_ = network->getInput(0)->getName();

    nvinfer1::Dims min_dims = input_dims_s2;
    min_dims.d[0] = batch_size_s2_;
    nvinfer1::Dims opt_dims = input_dims_s2;
    opt_dims.d[0] = batch_size_s2_;
    nvinfer1::Dims max_dims = input_dims_s2;
    max_dims.d[0] = batch_size_s1_;

    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kMIN, min_dims);
    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kOPT, opt_dims);
    profile->setDimensions(input_tensor_names_.c_str(), nvinfer1::OptProfileSelector::kMAX, max_dims);

    // config->setMinTimingIterations(2);
    // config->setAvgTimingIterations(1);
    config->addOptimizationProfile(profile);
    config->setMaxWorkspaceSize(3_GiB);
    return true;
}

std::vector<float> Profiler::infer(const bool separate_or_not, const size_t& num_test,
                 const int batch_idx, const int copy_method, const bool overload)
{
    float elapsed_time = 0;
    float elapsed_time_s1 = 0;
    float elapsed_time_s2 = 0;
    std::vector<float> metrics;
    if (separate_or_not) {
        CUDACHECK(cudaDeviceSynchronize());
        CUDACHECK(cudaEventRecord(infer_start, stream_));
        input_dims_s1.d[0] = batch_size_s1_;
        mContext_s1->setBindingDimensions(0, input_dims_s1);
        samplesCommon::BufferManager buffer_s1(mEngine_s1, batch_size_s1_);
        buffer_s1.copyInputToDevice();
        auto status_s1 = mContext_s1->enqueueV2(buffer_s1.getDeviceBindings().data(), stream_, nullptr);
        if (!status_s1) {
            std::cout << "Error when inferring S1 model" << std::endl;
        }
        CUDACHECK(cudaEventRecord(s1_end, stream_));
        CUDACHECK(cudaEventSynchronize(s1_end));

        std::vector<int> full_copy_list;
        for(int i = 0; i < batch_size_s1_; ++i)
        {
            full_copy_list.push_back(i);
        }
        random_shuffle(full_copy_list.begin(), full_copy_list.end());
        std::vector<int> copy_list;

        int next_batch_size = batch_size_s2_;
        if (overload) {
            next_batch_size = batch_size_s1_;
        }

        for(int i = 0; i < next_batch_size ; ++i){
            copy_list.push_back(full_copy_list[i]);
        }

        input_dims_s2.d[0] = next_batch_size;
        mContext_s2->setBindingDimensions(0, input_dims_s2);
        std::shared_ptr<samplesCommon::ManagedBuffer> srcPtr = buffer_s1.getImmediateBuffer(2);
        samplesCommon::BufferManager buffer_s2(mEngine_s2, batch_size_s1_,
                                srcPtr, &copy_list, copy_method);

        auto status_s2 = mContext_s2->enqueueV2(buffer_s2.getDeviceBindings().data(), stream_, nullptr);
        if (!status_s2) {
            std::cout << "Error when inferring S2 model" << std::endl;
        }
        CUDACHECK(cudaEventRecord(s2_end, stream_));
        CUDACHECK(cudaEventSynchronize(s2_end));
    
        CUDACHECK(cudaEventElapsedTime(&elapsed_time_s1, infer_start, s1_end));
        CUDACHECK(cudaEventElapsedTime(&elapsed_time_s2, s1_end, s2_end));
        CUDACHECK(cudaEventElapsedTime(&elapsed_time, infer_start, s2_end));
        metrics.push_back(elapsed_time_s1);
        metrics.push_back(elapsed_time_s2);
        metrics.push_back(elapsed_time);
    }
    else {
        CUDACHECK(cudaDeviceSynchronize());
        CUDACHECK(cudaEventRecord(infer_start, stream_));
        input_dims_s0.d[0] = batch_size_s1_;
        mContext_s0->setBindingDimensions(0, input_dims_s0);
        samplesCommon::BufferManager buffer_s0(mEngine_s0, batch_size_s1_);
        buffer_s0.copyInputToDevice();
        auto status_s0 = mContext_s0->enqueueV2(buffer_s0.getDeviceBindings().data(), stream_, nullptr);
        if (!status_s0) {
            std::cout << "Error when inferring the full model" << std::endl;
        }
        CUDACHECK(cudaEventRecord(s2_end, stream_));
        CUDACHECK(cudaEventSynchronize(s2_end));
    
        CUDACHECK(cudaEventElapsedTime(&elapsed_time, infer_start, s2_end));
        metrics.push_back(elapsed_time);
    }
    return metrics;
}

bool model_generation(const int start_point, const int end_point)
{
    PyRun_SimpleString("import sys");
    PyRun_SimpleString("sys.path.append('/home/slzhang/projects/ETBA/Inference/src/exit_placement')");
	PyObject* pModule = PyImport_ImportModule("model_export");
	if( pModule == NULL ){
		cout <<"module not found" << endl;
		return 1;
	}
	PyObject* pFunc = PyObject_GetAttrString(pModule, "model_export_func");
	if( !pFunc || !PyCallable_Check(pFunc)){
		cout <<"not found function model_export_func" << endl;
		return 0;
	}
    PyObject* args = Py_BuildValue("(ii)", start_point, end_point);
    PyObject* pRet = PyObject_CallObject(pFunc, args);
    Py_DECREF(args);
    Py_DECREF(pRet);
    return true;
}

int main(int argc, char** argv)
{
    std::string config_path = "/home/slzhang/projects/ETBA/Inference/src/exit_placement/profiler_config.json";
    FILE* config_fp = fopen(config_path.c_str(), "r");
    if(!config_fp){
        std::cout<<"failed to open config.json"<<endl;
        return -1;
    }
    char read_buffer[65536];

    rapidjson::FileReadStream config_fs(
        config_fp, read_buffer, sizeof(read_buffer));
    rapidjson::Document config_doc;
    config_doc.ParseStream(config_fs);

    std::ofstream outFile;
    Py_Initialize();
    int extend_max_block = 8;
    if (config_doc["seperate_or_not"].GetBool()){
        for (int start_point = 8; start_point < 25; start_point++)
        {
            // Do the pre test to determine the end point of stage1 network
            std::vector<float> pre_test_time;
            for (int post_block_num = 0; post_block_num < extend_max_block; post_block_num++)
            {
                int end_point = start_point + post_block_num;
                bool model_generated = model_generation(start_point, end_point);
                if(!model_generated){
                    std::cout<<"failed to export models"<<endl;
                    return -1;
                }
                Profiler pre_inst = Profiler(config_doc["bs_s1"].GetUint(), 
                                        config_doc["bs_s2"].GetUint(), 
                                        config_doc["bs_num"].GetUint(),
                                        nvinfer1::ILogger::Severity::kERROR);
                pre_inst.build_s1();
                pre_inst.build_s2();
                float pre_test_total_time = 0;
                for (int batch_idx = 0; batch_idx < pre_inst.batch_num_; batch_idx++) 
                {
                    std::vector<float> metrics = pre_inst.infer(true, config_doc["test_iter"].GetUint(), batch_idx, 
                                                    config_doc["copy_method"].GetUint());
                    pre_test_total_time += metrics[2];
                }
                std::cout << "Average elapsed time: " << pre_test_total_time/pre_inst.batch_num_
                            << " post_block_num: " + to_string(post_block_num)
                            << std::endl;
                pre_test_time.push_back(pre_test_total_time/pre_inst.batch_num_);
            }
            auto shortest_time = std::min_element(std::begin(pre_test_time), std::end(pre_test_time));
            int opt_post_block_num = std::distance(std::begin(pre_test_time), shortest_time);
            int end_point = start_point + opt_post_block_num;
            std::cout << "Opt end_point for start_point " << start_point << " is " << end_point << std::endl;
            bool opt_model_generated = model_generation(start_point, end_point);
            if(!opt_model_generated){
                std::cout<<"failed to export opt models"<<endl;
                return -1;
            }
            
            std::vector<float> avg_elapsed_time_s1;
            std::vector<float> avg_elapsed_time_s2;
            std::vector<float> avg_elapsed_time;
            std::vector<float> avg_elapsed_time_overload;
            int batch_size_s1 = config_doc["bs_s1"].GetUint();
            int batch_interval = config_doc["b_interval"].GetUint();
            for (int batch_size_s2 = batch_interval; batch_size_s2 <= batch_size_s1;
                     batch_size_s2 = batch_size_s2 + batch_interval)
            {
                // size_t batch_size_s2 = config_doc["bs_s2"].GetUint() * batch_scale / 4;
                Profiler inst = Profiler(batch_size_s1, batch_size_s2, 
                                        config_doc["bs_num"].GetUint(),
                                        nvinfer1::ILogger::Severity::kERROR);
                inst.build_s1();
                inst.build_s2();
                float total_elapsed_time_s1 = 0;
                float total_elapsed_time_s2 = 0;
                float total_elapsed_time = 0;
                float total_elapsed_time_overload = 0;
                for (int batch_idx = 0; batch_idx < inst.batch_num_; batch_idx++) 
                {
                    std::vector<float> metrics = inst.infer(config_doc["seperate_or_not"].GetBool(),
                                                config_doc["test_iter"].GetUint(), batch_idx, 
                                                config_doc["copy_method"].GetUint());
                    total_elapsed_time_s1 += metrics[0];
                    total_elapsed_time_s2 += metrics[1];
                    total_elapsed_time += metrics[2];
                    std::vector<float> metrics_overload = inst.infer(config_doc["seperate_or_not"].GetBool(),
                                                config_doc["test_iter"].GetUint(), batch_idx, 
                                                config_doc["copy_method"].GetUint(), true);
                    total_elapsed_time_overload += metrics_overload[2];
                }
                avg_elapsed_time_s1.push_back(total_elapsed_time_s1/inst.batch_num_);
                avg_elapsed_time_s2.push_back(total_elapsed_time_s2/inst.batch_num_);
                avg_elapsed_time.push_back(total_elapsed_time/inst.batch_num_);
                avg_elapsed_time_overload.push_back(total_elapsed_time_overload/inst.batch_num_);
                std::cout << "Average elapsed time: " << avg_elapsed_time_s1.back() << " + " 
                            << avg_elapsed_time_s2.back() << " = " << avg_elapsed_time.back() 
                            << " < " << avg_elapsed_time_overload.back()
                            << " (" + to_string(config_doc["bs_s1"].GetUint()) + " -> " + to_string(batch_size_s2) + ")"
                            << std::endl;
            }
            outFile.open("/home/slzhang/projects/ETBA/Inference/src/exit_placement/config_unipose_" + 
                            to_string(config_doc["bs_s1"].GetUint()) + ".csv", ios::app);
            outFile << start_point << ',' << end_point << ',';

            for (int i = 0; i < avg_elapsed_time.size(); ++i){
                outFile << avg_elapsed_time_s1.at(i) << ',';
                outFile << avg_elapsed_time_s2.at(i) << ',';
                outFile << avg_elapsed_time.at(i) << ',';
                outFile << avg_elapsed_time_overload.at(i) << ',';
                if (i == avg_elapsed_time.size() - 1) {outFile << endl;}
            }

            outFile.close();
        }
    }
    else {
        size_t batch_size_s1 = config_doc["bs_s1"].GetUint();
        size_t batch_size_s2 = config_doc["bs_s2"].GetUint();
        Profiler inst = Profiler(batch_size_s1, batch_size_s2, 
                                config_doc["bs_num"].GetUint(),
                                nvinfer1::ILogger::Severity::kERROR);
        inst.build_s0();
        float total_elapsed_time = 0;
        for (int batch_idx = 0; batch_idx < inst.batch_num_; batch_idx++) 
        {
            std::vector<float> metrics = inst.infer(config_doc["seperate_or_not"].GetBool(),
                                        config_doc["test_iter"].GetUint(), batch_idx, 
                                        config_doc["copy_method"].GetUint());
            total_elapsed_time += metrics[0];
        }
        float avg_elapsed_time = total_elapsed_time/inst.batch_num_;
        std::cout << "Average elapsed time of the full model: " 
                    << avg_elapsed_time << std::endl;
    }
    Py_Finalize();
    return 0;
}